#!/usr/bin/env python3
"""Read-only Meta Ads CLI batch audit helper.

The script intentionally uses only Python's standard library so it can ship as
part of the skill without adding an install step.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
READ_ONLY_ENV = "META_ADS_READ_ONLY"
WRITE_VERBS = {
    "activate",
    "archive",
    "create",
    "delete",
    "disable",
    "enable",
    "pause",
    "remove",
    "resume",
    "start",
    "stop",
    "update",
}
PRESETS = (
    "ua-creative-audit",
    "wasted-spend",
    "geo-quality",
    "video-retention",
    "funnel-dropoff",
)
DEFAULT_FIELDS = (
    "spend,impressions,clicks,ctr,cpc,reach,actions,action_values,"
    "video_p25_watched_actions,video_p50_watched_actions,"
    "video_p75_watched_actions,video_p100_watched_actions"
)
TTL_SECONDS = {
    "adaccount": 24 * 60 * 60,
    "adaccount_list": 24 * 60 * 60,
    "campaign": 6 * 60 * 60,
    "campaign_list": 6 * 60 * 60,
    "adset": 6 * 60 * 60,
    "adset_list": 6 * 60 * 60,
    "ad": 6 * 60 * 60,
    "ad_list": 6 * 60 * 60,
    "creative": 7 * 24 * 60 * 60,
    "thumbnail": 30 * 24 * 60 * 60,
}


TOKEN_PATTERNS = [
    re.compile(r"access_token=([^&\s]+)", flags=re.IGNORECASE),
    re.compile(r"\bEAA[A-Za-z0-9_\-]{8,}\b"),
    re.compile(
        r"(?i)\b(app_secret|client_secret)\b\s*[:=]\s*['\"]?[^'\"\s,}]+"
    ),
]


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_z(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso_z(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def redact_text(value: str) -> str:
    redacted = value
    redacted = TOKEN_PATTERNS[0].sub("access_token=[REDACTED]", redacted)
    redacted = TOKEN_PATTERNS[1].sub("[REDACTED_META_TOKEN]", redacted)
    redacted = TOKEN_PATTERNS[2].sub(lambda match: f"{match.group(1)}=[REDACTED]", redacted)
    return redacted


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, dict):
        return {key: redact_value(item) for key, item in value.items()}
    return value


class UnsafeCommandError(ValueError):
    """Raised when a command is not read-only."""


@dataclass
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


class RedactingRunner:
    def __init__(self, *, timeout: int = 90, retries: int = 2, sleep_seconds: float = 1.0):
        self.timeout = timeout
        self.retries = retries
        self.sleep_seconds = sleep_seconds
        self.commands_run: list[list[str]] = []

    def validate_read_only(self, command: list[str]) -> None:
        lower = {part.lower() for part in command}
        blocked = sorted(lower & WRITE_VERBS)
        if blocked:
            raise UnsafeCommandError(
                f"Refusing non-read-only Meta Ads command containing: {', '.join(blocked)}"
            )

    def run(self, command: list[str], *, env: dict[str, str] | None = None) -> CommandResult:
        self.validate_read_only(command)
        merged_env = os.environ.copy()
        merged_env[READ_ONLY_ENV] = "1"
        if env:
            merged_env.update(env)
        merged_env[READ_ONLY_ENV] = "1"

        last_result: CommandResult | None = None
        for attempt in range(self.retries + 1):
            self.commands_run.append(command)
            try:
                completed = subprocess.run(
                    command,
                    check=False,
                    env=merged_env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=self.timeout,
                )
                result = CommandResult(
                    command=command,
                    returncode=completed.returncode,
                    stdout=redact_text(completed.stdout or ""),
                    stderr=redact_text(completed.stderr or ""),
                )
            except FileNotFoundError:
                result = CommandResult(command, 127, "", "command not found")
            except subprocess.TimeoutExpired as error:
                result = CommandResult(
                    command,
                    124,
                    redact_text(error.stdout or ""),
                    redact_text(error.stderr or "command timed out"),
                )

            last_result = result
            if result.returncode == 0:
                return result
            if result.returncode not in {4, 124} or attempt == self.retries:
                return result
            time.sleep(self.sleep_seconds * (2**attempt))

        assert last_result is not None
        return last_result

    def run_json(self, command: list[str], *, env: dict[str, str] | None = None) -> Any:
        result = self.run(command, env=env)
        if result.returncode != 0:
            raise RuntimeError(
                f"Command failed with exit code {result.returncode}: "
                f"{' '.join(command)}\n{result.stderr or result.stdout}"
            )
        payload = result.stdout.strip()
        if not payload:
            return []
        try:
            return json.loads(payload)
        except json.JSONDecodeError as error:
            raise RuntimeError(
                f"Command did not return JSON: {' '.join(command)}\n{payload[:500]}"
            ) from error


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    writes: int = 0
    stale: int = 0
    corrupt: int = 0
    pruned: int = 0


@dataclass
class CacheEntry:
    hit: bool
    data: Any | None = None
    reason: str = "miss"


class CacheStore:
    def __init__(self, root: Path, *, now: datetime | None = None):
        self.root = root
        self.now = now or utc_now()
        self.stats = CacheStats()

    def path_for(self, account_id: str, entity_type: str, entity_id: str) -> Path:
        return self.root / safe_path_part(account_id) / safe_path_part(entity_type) / f"{safe_path_part(entity_id)}.json"

    def asset_path_for(self, assets_dir: Path, creative_id: str) -> Path:
        return assets_dir / f"{safe_path_part(creative_id)}.jpg"

    def read(
        self,
        account_id: str,
        entity_type: str,
        entity_id: str,
        *,
        refresh: bool = False,
    ) -> CacheEntry:
        if refresh:
            self.stats.misses += 1
            return CacheEntry(False, reason="refresh_requested")

        path = self.path_for(account_id, entity_type, entity_id)
        if not path.exists():
            self.stats.misses += 1
            return CacheEntry(False, reason="missing")

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.stats.corrupt += 1
            self.stats.misses += 1
            return CacheEntry(False, reason="corrupt")

        metadata = payload.get("_cache", {}) if isinstance(payload, dict) else {}
        expected = {
            "schema_version": SCHEMA_VERSION,
            "account_id": account_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
        }
        for key, expected_value in expected.items():
            if metadata.get(key) != expected_value:
                self.stats.misses += 1
                return CacheEntry(False, reason=f"metadata_{key}_mismatch")

        ttl = int(metadata.get("ttl_seconds", TTL_SECONDS.get(entity_type, 0)))
        cached_at = metadata.get("cached_at")
        try:
            cached_time = parse_iso_z(cached_at)
        except (TypeError, ValueError):
            self.stats.misses += 1
            return CacheEntry(False, reason="invalid_cached_at")

        if ttl >= 0 and self.now > cached_time + timedelta(seconds=ttl):
            self.stats.stale += 1
            self.stats.misses += 1
            return CacheEntry(False, reason="expired")

        self.stats.hits += 1
        return CacheEntry(True, data=payload.get("data"), reason="hit")

    def write(
        self,
        account_id: str,
        entity_type: str,
        entity_id: str,
        data: Any,
        *,
        source_command: list[str] | None = None,
    ) -> None:
        path = self.path_for(account_id, entity_type, entity_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        ttl = TTL_SECONDS.get(entity_type, 6 * 60 * 60)
        payload = {
            "_cache": {
                "schema_version": SCHEMA_VERSION,
                "cached_at": iso_z(self.now),
                "account_id": account_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "ttl_seconds": ttl,
                "source_command": redact_text(" ".join(source_command or [])),
                "redacted": True,
            },
            "data": redact_value(data),
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.stats.writes += 1

    def prune(self, older_than_days: int) -> None:
        if older_than_days < 0 or not self.root.exists():
            return
        cutoff = self.now - timedelta(days=older_than_days)
        for path in self.root.rglob("*.json"):
            try:
                if datetime.fromtimestamp(path.stat().st_mtime, tz=UTC) < cutoff:
                    path.unlink()
                    self.stats.pruned += 1
            except OSError:
                continue


def safe_path_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("._") or "unknown"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a read-only Meta Ads batch audit.")
    parser.add_argument("--accounts", required=True, help="`all` or comma-separated act_... IDs")
    parser.add_argument("--since", help="Inclusive start date, YYYY-MM-DD")
    parser.add_argument("--until", help="Inclusive end date, YYYY-MM-DD")
    parser.add_argument("--last-days", type=int, help="Inclusive lookback ending on --today/today")
    parser.add_argument("--output", default="reports/meta_ads_audit.json")
    parser.add_argument("--preset", choices=PRESETS, default="ua-creative-audit")
    parser.add_argument("--cache-dir", default=".cache/meta-ads")
    parser.add_argument("--assets-dir", default="reports/assets")
    parser.add_argument("--refresh-entities", action="store_true")
    parser.add_argument("--refresh-creatives", action="store_true")
    parser.add_argument("--no-download-assets", action="store_true")
    parser.add_argument("--prune-cache-days", type=int)
    parser.add_argument("--today", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def resolve_date_window(args: argparse.Namespace) -> tuple[date, date, list[str]]:
    warnings: list[str] = []
    today = date.fromisoformat(args.today) if args.today else date.today()

    has_explicit = bool(args.since or args.until)
    if args.last_days and has_explicit:
        raise ValueError("Use either --last-days or --since/--until, not both")

    if args.last_days:
        if args.last_days <= 0:
            raise ValueError("--last-days must be positive")
        until = today
        since = until - timedelta(days=args.last_days - 1)
    else:
        if args.since and args.until:
            since = date.fromisoformat(args.since)
            until = date.fromisoformat(args.until)
        elif args.since or args.until:
            raise ValueError("--since and --until must be provided together")
        else:
            until = today
            since = until - timedelta(days=29)

    if since > until:
        raise ValueError("--since must be on or before --until")

    inclusive_days = (until - since).days + 1
    if inclusive_days == 31:
        warnings.append(
            f"Date range {since} to {until} is 31 inclusive days; "
            "for last 30 days including today use "
            f"{until - timedelta(days=29)} to {until}."
        )
    return since, until, warnings


def normalize_records(payload: Any) -> list[dict[str, Any]]:
    payload = redact_value(payload)
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            return [data]
        return [payload]
    return []


def entity_id(record: dict[str, Any], *fallbacks: str) -> str:
    for key in ("id", *fallbacks):
        value = record.get(key)
        if value:
            return str(value)
    return "unknown"


def action_value(record: dict[str, Any], action_type: str, *, field: str = "actions") -> float:
    actions = record.get(field) or []
    if isinstance(actions, dict):
        actions = [actions]
    total = 0.0
    if not isinstance(actions, list):
        return 0.0
    for action in actions:
        if not isinstance(action, dict):
            continue
        if action.get("action_type") == action_type:
            total += to_float(action.get("value"))
    return total


def to_float(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def safe_ratio(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def find_creative_id(ad: dict[str, Any]) -> str | None:
    for key in ("creative_id", "ad_creative_id"):
        value = ad.get(key)
        if value:
            return str(value)
    creative = ad.get("creative")
    if isinstance(creative, dict) and creative.get("id"):
        return str(creative["id"])
    return None


def extract_creative_fields(creative: dict[str, Any]) -> dict[str, Any]:
    object_story_spec = creative.get("object_story_spec") or {}
    link_data = object_story_spec.get("link_data") or {}
    video_data = object_story_spec.get("video_data") or {}
    asset_feed_spec = creative.get("asset_feed_spec") or {}

    cta = (
        creative.get("call_to_action_type")
        or link_data.get("call_to_action", {}).get("type")
        or video_data.get("call_to_action", {}).get("type")
    )
    destination = (
        creative.get("url_tags")
        or creative.get("link_url")
        or link_data.get("link")
        or video_data.get("call_to_action", {}).get("value", {}).get("link")
    )
    primary_text = (
        creative.get("body")
        or link_data.get("message")
        or video_data.get("message")
    )
    headline = (
        creative.get("title")
        or creative.get("name")
        or link_data.get("name")
        or video_data.get("title")
    )
    asset_images = []
    for image in asset_feed_spec.get("images", []) if isinstance(asset_feed_spec, dict) else []:
        if isinstance(image, dict):
            asset_images.append(
                {
                    "hash": image.get("hash"),
                    "url": image.get("url"),
                    "url_128": image.get("url_128"),
                }
            )

    return {
        "id": entity_id(creative),
        "name": creative.get("name"),
        "thumbnail_url": creative.get("thumbnail_url"),
        "image_url": creative.get("image_url") or link_data.get("image_url"),
        "image_hash": creative.get("image_hash") or link_data.get("image_hash"),
        "video_id": creative.get("video_id") or video_data.get("video_id"),
        "cta": cta,
        "destination_url": destination,
        "primary_text": primary_text,
        "headline": headline,
        "asset_feed_images": asset_images,
        "creative_visual_family": classify_visual_family(creative),
    }


def classify_visual_family(creative: dict[str, Any]) -> str:
    extracted = {
        "image_hash": creative.get("image_hash"),
        "image_url": creative.get("image_url"),
        "thumbnail_url": creative.get("thumbnail_url"),
        "video_id": creative.get("video_id"),
    }
    for key, value in extracted.items():
        if value:
            return f"{key}:{value}"
    object_story_spec = creative.get("object_story_spec") or {}
    for block_name in ("link_data", "video_data"):
        block = object_story_spec.get(block_name) or {}
        for key in ("image_hash", "image_url", "video_id"):
            if block.get(key):
                return f"{key}:{block[key]}"
    return f"creative:{entity_id(creative)}"


def detect_level_support(runner: RedactingRunner) -> bool:
    result = runner.run(["meta", "ads", "insights", "get", "--help"])
    if result.returncode != 0:
        return False
    return "--level" in result.stdout or " level" in result.stdout


def command_with_dates(command: list[str], since: date, until: date) -> list[str]:
    return [*command, "--since", since.isoformat(), "--until", until.isoformat()]


def cached_list(
    *,
    runner: RedactingRunner,
    cache: CacheStore,
    account_id: str,
    entity_type: str,
    command: list[str],
    env: dict[str, str],
    refresh: bool,
    list_id: str = "_list",
) -> list[dict[str, Any]]:
    list_type = f"{entity_type}_list"
    cached = cache.read(account_id, list_type, list_id, refresh=refresh)
    if cached.hit:
        return normalize_records(cached.data)
    payload = runner.run_json(command, env=env)
    records = normalize_records(payload)
    cache.write(account_id, list_type, list_id, records, source_command=command)
    for record in records:
        cache.write(
            account_id,
            entity_type,
            entity_id(record),
            record,
            source_command=command,
        )
    return records


def get_cached_creative(
    *,
    runner: RedactingRunner,
    cache: CacheStore,
    account_id: str,
    creative_id: str,
    refresh: bool,
) -> dict[str, Any]:
    cached = cache.read(account_id, "creative", creative_id, refresh=refresh)
    if cached.hit and isinstance(cached.data, dict):
        return cached.data
    command = ["meta", "--output", "json", "ads", "creative", "get", creative_id]
    payload = runner.run_json(command, env={"AD_ACCOUNT_ID": account_id})
    records = normalize_records(payload)
    creative = records[0] if records else {"id": creative_id}
    cache.write(account_id, "creative", creative_id, creative, source_command=command)
    return creative


def get_insights(
    *,
    runner: RedactingRunner,
    account_id: str,
    since: date,
    until: date,
    level: str,
    level_supported: bool,
    entities: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    env = {"AD_ACCOUNT_ID": account_id}
    base = [
        "meta",
        "--output",
        "json",
        "ads",
        "insights",
        "get",
        "--fields",
        DEFAULT_FIELDS,
    ]
    if level == "account":
        command = command_with_dates(base, since, until)
        return [attach_account(record, account_id) for record in normalize_records(runner.run_json(command, env=env))]

    if level_supported:
        command = command_with_dates([*base, "--level", level], since, until)
        try:
            return [
                attach_account(record, account_id)
                for record in normalize_records(runner.run_json(command, env=env))
            ]
        except RuntimeError:
            # Some beta builds advertise --level but reject specific values.
            # Fall through to the scoped per-entity calls.
            pass

    id_flag = {
        "campaign": "--campaign_id",
        "adset": "--adset_id",
        "ad": "--ad_id",
    }[level]
    records: list[dict[str, Any]] = []
    for entity in entities or []:
        scoped_id = entity_id(entity)
        scoped = command_with_dates([*base, id_flag, entity_id(entity)], since, until)
        for record in normalize_records(runner.run_json(scoped, env=env)):
            record.setdefault(f"{level}_id", scoped_id)
            records.append(attach_account(record, account_id))
    return records


def get_breakdown(
    *,
    runner: RedactingRunner,
    account_id: str,
    since: date,
    until: date,
    breakdown: str,
) -> list[dict[str, Any]]:
    command = command_with_dates(
        [
            "meta",
            "--output",
            "json",
            "ads",
            "insights",
            "get",
            "--fields",
            DEFAULT_FIELDS,
            "--breakdowns",
            breakdown,
        ],
        since,
        until,
    )
    try:
        return [
            attach_account(record, account_id)
            for record in normalize_records(runner.run_json(command, env={"AD_ACCOUNT_ID": account_id}))
        ]
    except RuntimeError as error:
        return [{"account_id": account_id, "breakdown": breakdown, "error": redact_text(str(error))}]


def attach_account(record: dict[str, Any], account_id: str) -> dict[str, Any]:
    if "account_id" not in record:
        record = dict(record)
        record["account_id"] = account_id
    return record


def reconcile(
    *,
    account_rows: list[dict[str, Any]],
    campaign_rows: list[dict[str, Any]],
    adset_rows: list[dict[str, Any]],
    ad_rows: list[dict[str, Any]],
    action_types: tuple[str, ...] = ("purchase",),
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    levels = {
        "account": account_rows,
        "campaign": campaign_rows,
        "adset": adset_rows,
        "ad": ad_rows,
    }
    for account_id in sorted({str(row.get("account_id")) for row in account_rows if row.get("account_id")}):
        account_level = [row for row in account_rows if str(row.get("account_id")) == account_id]
        for action_type in action_types:
            totals = {
                level: sum(
                    action_value(row, action_type)
                    for row in rows
                    if str(row.get("account_id")) == account_id
                )
                for level, rows in levels.items()
            }
            for parent, child in (("account", "campaign"), ("campaign", "adset"), ("adset", "ad")):
                gap = totals[parent] - totals[child]
                if gap > 0.000001:
                    warnings.append(
                        {
                            "type": "reconciliation_gap",
                            "account_id": account_id,
                            "action_type": action_type,
                            "parent_level": parent,
                            "child_level": child,
                            "parent_total": totals[parent],
                            "child_total": totals[child],
                            "gap": gap,
                            "message": (
                                f"{format_number(gap)} {action_type} are visible at "
                                f"{parent}/higher level but not traceable to listed {child} rows. "
                                "Possible deleted/hidden ads, attribution delay, or API visibility gap."
                            ),
                        }
                    )
            if not account_level and any(totals.values()):
                warnings.append(
                    {
                        "type": "reconciliation_missing_account",
                        "account_id": account_id,
                        "action_type": action_type,
                        "message": "Lower-level rows exist without an account-level row.",
                    }
                )
    return warnings


def format_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.2f}"


def summarize_ua_creative_audit(
    *,
    ads: list[dict[str, Any]],
    creatives: list[dict[str, Any]],
    ad_insights: list[dict[str, Any]],
) -> dict[str, Any]:
    creative_by_id = {entity_id(creative): creative for creative in creatives}
    ad_to_creative = {entity_id(ad): find_creative_id(ad) for ad in ads}
    rows: list[dict[str, Any]] = []
    for insight in ad_insights:
        ad_id = str(insight.get("ad_id") or insight.get("id") or insight.get("ad.id") or "")
        creative_id = str(insight.get("creative_id") or ad_to_creative.get(ad_id) or "")
        creative = creative_by_id.get(creative_id, {})
        spend = to_float(insight.get("spend"))
        purchases = action_value(insight, "purchase")
        purchase_value = action_value(insight, "purchase", field="action_values")
        checkouts = action_value(insight, "initiate_checkout")
        registrations = action_value(insight, "complete_registration")
        video_completions = action_value(insight, "video_view", field="video_p100_watched_actions")
        impressions = to_float(insight.get("impressions"))
        row = {
            "account_id": insight.get("account_id"),
            "ad_id": ad_id,
            "creative_id": creative_id,
            "creative_visual_family": creative.get("creative_visual_family") or classify_visual_family(creative),
            "spend": spend,
            "purchases": purchases,
            "cpa": safe_ratio(spend, purchases),
            "roas": safe_ratio(purchase_value, spend),
            "checkout_without_purchase": max(checkouts - purchases, 0.0),
            "registration_to_purchase_gap": max(registrations - purchases, 0.0),
            "video_completion_rate": safe_ratio(video_completions, impressions),
        }
        rows.append(row)

    return {
        "ranked_by_purchases": sorted(rows, key=lambda row: row["purchases"], reverse=True),
        "ranked_by_cpa": sorted(
            [row for row in rows if row["cpa"] is not None],
            key=lambda row: row["cpa"],
        ),
        "ranked_by_roas": sorted(
            [row for row in rows if row["roas"] is not None],
            key=lambda row: row["roas"],
            reverse=True,
        ),
        "spend_with_zero_purchase": sorted(
            [row for row in rows if row["spend"] > 0 and row["purchases"] == 0],
            key=lambda row: row["spend"],
            reverse=True,
        ),
        "checkout_without_purchase": sorted(
            rows,
            key=lambda row: row["checkout_without_purchase"],
            reverse=True,
        ),
        "registration_to_purchase_gap": sorted(
            rows,
            key=lambda row: row["registration_to_purchase_gap"],
            reverse=True,
        ),
        "video_completion_rate": sorted(
            [row for row in rows if row["video_completion_rate"] is not None],
            key=lambda row: row["video_completion_rate"],
            reverse=True,
        ),
        "creative_visual_family": summarize_visual_families(rows),
    }


def summarize_visual_families(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        family = row["creative_visual_family"] or "unknown"
        bucket = grouped.setdefault(
            family,
            {"creative_visual_family": family, "spend": 0.0, "purchases": 0.0, "ads": 0},
        )
        bucket["spend"] += row["spend"]
        bucket["purchases"] += row["purchases"]
        bucket["ads"] += 1
    for bucket in grouped.values():
        bucket["cpa"] = safe_ratio(bucket["spend"], bucket["purchases"])
    return sorted(grouped.values(), key=lambda row: (row["purchases"], -row["spend"]), reverse=True)


def build_preset_reports(
    preset: str,
    *,
    ads: list[dict[str, Any]],
    creatives: list[dict[str, Any]],
    ad_insights: list[dict[str, Any]],
) -> dict[str, Any]:
    if preset == "ua-creative-audit":
        return {preset: summarize_ua_creative_audit(ads=ads, creatives=creatives, ad_insights=ad_insights)}
    if preset == "wasted-spend":
        ua = summarize_ua_creative_audit(ads=ads, creatives=creatives, ad_insights=ad_insights)
        return {preset: {"spend_with_zero_purchase": ua["spend_with_zero_purchase"]}}
    if preset == "video-retention":
        ua = summarize_ua_creative_audit(ads=ads, creatives=creatives, ad_insights=ad_insights)
        return {preset: {"video_completion_rate": ua["video_completion_rate"]}}
    if preset == "funnel-dropoff":
        ua = summarize_ua_creative_audit(ads=ads, creatives=creatives, ad_insights=ad_insights)
        return {
            preset: {
                "checkout_without_purchase": ua["checkout_without_purchase"],
                "registration_to_purchase_gap": ua["registration_to_purchase_gap"],
            }
        }
    return {preset: {"note": "Geo quality preset uses breakdown_country and breakdown_platform tables."}}


def download_thumbnail(
    *,
    cache: CacheStore,
    assets_dir: Path,
    account_id: str,
    creative_id: str,
    thumbnail_url: str,
    refresh: bool,
) -> dict[str, Any]:
    path = cache.asset_path_for(assets_dir, creative_id)
    cached = cache.read(account_id, "thumbnail", creative_id, refresh=refresh)
    if cached.hit and path.exists():
        return {"creative_id": creative_id, "path": str(path), "cached": True}

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(thumbnail_url, timeout=30) as response:
            path.write_bytes(response.read())
        cache.write(
            account_id,
            "thumbnail",
            creative_id,
            {"path": str(path), "thumbnail_url": thumbnail_url},
            source_command=["download", thumbnail_url],
        )
        return {"creative_id": creative_id, "path": str(path), "cached": False}
    except (OSError, urllib.error.URLError) as error:
        return {
            "creative_id": creative_id,
            "path": str(path),
            "error": redact_text(str(error)),
            "cached": False,
        }


def run_audit(args: argparse.Namespace, *, runner: RedactingRunner | None = None) -> dict[str, Any]:
    since, until, warnings = resolve_date_window(args)
    now = utc_now()
    cache = CacheStore(Path(args.cache_dir), now=now)
    if args.prune_cache_days is not None:
        cache.prune(args.prune_cache_days)
    runner = runner or RedactingRunner()
    level_supported = detect_level_support(runner)

    accounts: list[dict[str, Any]]
    if args.accounts == "all":
        accounts = cached_list(
            runner=runner,
            cache=cache,
            account_id="global",
            entity_type="adaccount",
            command=["meta", "--output", "json", "ads", "adaccount", "list"],
            env={},
            refresh=args.refresh_entities,
        )
    else:
        accounts = [{"id": account_id.strip()} for account_id in args.accounts.split(",") if account_id.strip()]

    campaigns: list[dict[str, Any]] = []
    adsets: list[dict[str, Any]] = []
    ads: list[dict[str, Any]] = []
    creatives: list[dict[str, Any]] = []
    assets: list[dict[str, Any]] = []
    account_insights: list[dict[str, Any]] = []
    campaign_insights: list[dict[str, Any]] = []
    adset_insights: list[dict[str, Any]] = []
    ad_insights: list[dict[str, Any]] = []
    breakdown_country: list[dict[str, Any]] = []
    breakdown_platform: list[dict[str, Any]] = []
    seen_creatives: set[tuple[str, str]] = set()

    for account in accounts:
        account_id = entity_id(account, "account_id")
        env = {"AD_ACCOUNT_ID": account_id}
        account_campaigns = cached_list(
            runner=runner,
            cache=cache,
            account_id=account_id,
            entity_type="campaign",
            command=["meta", "--output", "json", "ads", "campaign", "list"],
            env=env,
            refresh=args.refresh_entities,
        )
        campaigns.extend(attach_account(record, account_id) for record in account_campaigns)

        account_adsets: list[dict[str, Any]] = []
        for campaign in account_campaigns:
            campaign_id = entity_id(campaign)
            records = cached_list(
                runner=runner,
                cache=cache,
                account_id=account_id,
                entity_type="adset",
                command=["meta", "--output", "json", "ads", "adset", "list", "--campaign_id", campaign_id],
                env=env,
                refresh=args.refresh_entities,
                list_id=f"campaign_{campaign_id}",
            )
            for record in records:
                record = attach_account(record, account_id)
                record.setdefault("campaign_id", campaign_id)
                account_adsets.append(record)
        adsets.extend(account_adsets)

        account_ads: list[dict[str, Any]] = []
        for adset in account_adsets:
            adset_id = entity_id(adset)
            records = cached_list(
                runner=runner,
                cache=cache,
                account_id=account_id,
                entity_type="ad",
                command=["meta", "--output", "json", "ads", "ad", "list", "--adset_id", adset_id],
                env=env,
                refresh=args.refresh_entities,
                list_id=f"adset_{adset_id}",
            )
            for record in records:
                record = attach_account(record, account_id)
                record.setdefault("adset_id", adset_id)
                account_ads.append(record)
        ads.extend(account_ads)

        for ad in account_ads:
            creative_id = find_creative_id(ad)
            if not creative_id:
                continue
            creative_key = (account_id, creative_id)
            if creative_key in seen_creatives:
                continue
            seen_creatives.add(creative_key)
            creative = extract_creative_fields(
                get_cached_creative(
                    runner=runner,
                    cache=cache,
                    account_id=account_id,
                    creative_id=creative_id,
                    refresh=args.refresh_creatives,
                )
            )
            creative["account_id"] = account_id
            creatives.append(creative)
            if (
                creative.get("thumbnail_url")
                and not args.no_download_assets
            ):
                assets.append(
                    download_thumbnail(
                        cache=cache,
                        assets_dir=Path(args.assets_dir),
                        account_id=account_id,
                        creative_id=creative_id,
                        thumbnail_url=str(creative["thumbnail_url"]),
                        refresh=args.refresh_creatives,
                    )
                )

        account_insights.extend(
            get_insights(
                runner=runner,
                account_id=account_id,
                since=since,
                until=until,
                level="account",
                level_supported=level_supported,
            )
        )
        campaign_insights.extend(
            get_insights(
                runner=runner,
                account_id=account_id,
                since=since,
                until=until,
                level="campaign",
                level_supported=level_supported,
                entities=account_campaigns,
            )
        )
        adset_insights.extend(
            get_insights(
                runner=runner,
                account_id=account_id,
                since=since,
                until=until,
                level="adset",
                level_supported=level_supported,
                entities=account_adsets,
            )
        )
        ad_insights.extend(
            get_insights(
                runner=runner,
                account_id=account_id,
                since=since,
                until=until,
                level="ad",
                level_supported=level_supported,
                entities=account_ads,
            )
        )
        breakdown_country.extend(
            get_breakdown(
                runner=runner,
                account_id=account_id,
                since=since,
                until=until,
                breakdown="country",
            )
        )
        breakdown_platform.extend(
            get_breakdown(
                runner=runner,
                account_id=account_id,
                since=since,
                until=until,
                breakdown="publisher_platform",
            )
        )

    reconciliation_warnings = reconcile(
        account_rows=account_insights,
        campaign_rows=campaign_insights,
        adset_rows=adset_insights,
        ad_rows=ad_insights,
    )
    report = {
        "metadata": {
            "generated_at": iso_z(now),
            "since": since.isoformat(),
            "until": until.isoformat(),
            "inclusive_days": (until - since).days + 1,
            "preset": args.preset,
            "read_only_env": "1",
            "insights_level_supported": level_supported,
            "cache": cache.stats.__dict__,
        },
        "warnings": [{"type": "date_window", "message": warning} for warning in warnings]
        + reconciliation_warnings,
        "tables": {
            "accounts": accounts,
            "campaigns": campaigns,
            "adsets": adsets,
            "ads": ads,
            "creatives": creatives,
            "insights_account": account_insights,
            "insights_campaign": campaign_insights,
            "insights_adset": adset_insights,
            "insights_ad": ad_insights,
            "breakdowns_country": breakdown_country,
            "breakdowns_platform": breakdown_platform,
            "assets": assets,
        },
        "preset_reports": build_preset_reports(
            args.preset,
            ads=ads,
            creatives=creatives,
            ad_insights=ad_insights,
        ),
    }
    return redact_value(report)


def write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        report = run_audit(args)
        write_report(report, Path(args.output))
    except (RuntimeError, UnsafeCommandError, ValueError) as error:
        print(redact_text(str(error)), file=sys.stderr)
        return 1
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
