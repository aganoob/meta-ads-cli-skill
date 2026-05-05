from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "meta-ads-cli" / "scripts" / "meta_ads_audit.py"


def load_module():
    spec = importlib.util.spec_from_file_location("meta_ads_audit", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeRunner:
    def __init__(self, *, level_supported: bool = True):
        self.level_supported = level_supported
        self.commands_run: list[list[str]] = []

    def run(self, command, *, env=None):
        self.commands_run.append(command)
        stdout = "usage: insights get --level ad" if self.level_supported else "usage"
        return self.result(command, 0, stdout, "")

    def run_json(self, command, *, env=None):
        self.commands_run.append(command)
        joined = " ".join(command)
        account_id = (env or {}).get("AD_ACCOUNT_ID", "act_1")
        if " campaign list" in joined:
            return [{"id": "camp_1", "name": "Campaign"}]
        if " adset list" in joined:
            return [{"id": "adset_1", "name": "Ad Set", "campaign_id": "camp_1"}]
        if " ad list" in joined:
            return [
                {
                    "id": "ad_1",
                    "name": "Ad",
                    "adset_id": "adset_1",
                    "creative": {"id": "creative_1"},
                }
            ]
        if " creative get creative_1" in joined:
            return {
                "id": "creative_1",
                "name": "Creative",
                "thumbnail_url": "https://example.test/thumb.jpg",
                "image_hash": "hash_1",
                "body": "Primary",
                "title": "Headline",
                "call_to_action_type": "SHOP_NOW",
                "link_url": "https://example.test",
            }
        if "--breakdowns country" in joined:
            return [{"account_id": account_id, "country": "US", "spend": "10"}]
        if "--breakdowns publisher_platform" in joined:
            return [{"account_id": account_id, "publisher_platform": "facebook", "spend": "10"}]
        if "--level ad" in joined:
            return [
                {
                    "account_id": account_id,
                    "ad_id": "ad_1",
                    "spend": "50",
                    "impressions": "1000",
                    "actions": [{"action_type": "purchase", "value": "4"}],
                    "action_values": [{"action_type": "purchase", "value": "120"}],
                }
            ]
        if "--level adset" in joined:
            return [
                {
                    "account_id": account_id,
                    "adset_id": "adset_1",
                    "actions": [{"action_type": "purchase", "value": "6"}],
                }
            ]
        if "--level campaign" in joined:
            return [
                {
                    "account_id": account_id,
                    "campaign_id": "camp_1",
                    "actions": [{"action_type": "purchase", "value": "6"}],
                }
            ]
        if " insights get" in joined:
            return [
                {
                    "account_id": account_id,
                    "actions": [{"action_type": "purchase", "value": "6"}],
                }
            ]
        return []

    @staticmethod
    def result(command, returncode, stdout, stderr):
        class Result:
            pass

        result = Result()
        result.command = command
        result.returncode = returncode
        result.stdout = stdout
        result.stderr = stderr
        return result


class ListRunner:
    def __init__(self):
        self.calls = 0

    def run_json(self, command, *, env=None):
        self.calls += 1
        return [{"id": command[-1], "name": command[-1]}]


class MetaAdsAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()

    def test_resolves_last_30_days_inclusive(self) -> None:
        args = self.module.parse_args(
            ["--accounts", "act_1", "--last-days", "30", "--today", "2026-05-05"]
        )

        since, until, warnings = self.module.resolve_date_window(args)

        self.assertEqual(str(since), "2026-04-06")
        self.assertEqual(str(until), "2026-05-05")
        self.assertEqual(warnings, [])

    def test_warns_on_31_day_explicit_window(self) -> None:
        args = self.module.parse_args(
            [
                "--accounts",
                "act_1",
                "--since",
                "2026-04-05",
                "--until",
                "2026-05-05",
            ]
        )

        _, _, warnings = self.module.resolve_date_window(args)

        self.assertEqual(len(warnings), 1)
        self.assertIn("31 inclusive days", warnings[0])
        self.assertIn("2026-04-06 to 2026-05-05", warnings[0])

    def test_redacts_tokens_and_secrets(self) -> None:
        text = (
            "url?access_token=EAABadToken123&x=1 "
            "EAAabcdefghi12345 app_secret: supersecret client_secret=other"
        )

        redacted = self.module.redact_text(text)

        self.assertNotIn("EAABadToken123", redacted)
        self.assertNotIn("supersecret", redacted)
        self.assertNotIn("other", redacted)
        self.assertIn("access_token=[REDACTED]", redacted)
        self.assertIn("app_secret=[REDACTED]", redacted)

    def test_runner_rejects_write_commands(self) -> None:
        runner = self.module.RedactingRunner()

        with self.assertRaises(self.module.UnsafeCommandError):
            runner.validate_read_only(["meta", "ads", "campaign", "update", "camp_1"])

    def test_cache_metadata_ttl_and_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            now = datetime(2026, 5, 5, tzinfo=UTC)
            cache = self.module.CacheStore(Path(tmp), now=now)
            cache.write(
                "act_1",
                "creative",
                "creative_1",
                {"id": "creative_1"},
                source_command=["meta", "creative", "get", "creative_1"],
            )

            path = cache.path_for("act_1", "creative", "creative_1")
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["_cache"]["schema_version"], 1)
            self.assertEqual(payload["_cache"]["entity_type"], "creative")
            self.assertEqual(payload["_cache"]["ttl_seconds"], 7 * 24 * 60 * 60)
            self.assertTrue(cache.read("act_1", "creative", "creative_1").hit)

            future_cache = self.module.CacheStore(
                Path(tmp), now=now + timedelta(days=8)
            )
            self.assertFalse(
                future_cache.read("act_1", "creative", "creative_1").hit
            )
            self.assertFalse(
                cache.read("act_1", "creative", "creative_1", refresh=True).hit
            )

    def test_prunes_old_cache_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = self.module.CacheStore(
                Path(tmp), now=datetime(2026, 5, 5, tzinfo=UTC)
            )
            cache.write("act_1", "ad", "ad_1", {"id": "ad_1"})
            path = cache.path_for("act_1", "ad", "ad_1")
            old = datetime(2026, 1, 1, tzinfo=UTC).timestamp()
            os.utime(path, (old, old))

            cache.prune(90)

            self.assertFalse(path.exists())
            self.assertEqual(cache.stats.pruned, 1)

    def test_cached_lists_are_scoped_by_list_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = self.module.CacheStore(
                Path(tmp), now=datetime(2026, 5, 5, tzinfo=UTC)
            )
            runner = ListRunner()

            first = self.module.cached_list(
                runner=runner,
                cache=cache,
                account_id="act_1",
                entity_type="adset",
                command=["meta", "ads", "adset", "list", "--campaign_id", "camp_1"],
                env={},
                refresh=False,
                list_id="campaign_camp_1",
            )
            second = self.module.cached_list(
                runner=runner,
                cache=cache,
                account_id="act_1",
                entity_type="adset",
                command=["meta", "ads", "adset", "list", "--campaign_id", "camp_2"],
                env={},
                refresh=False,
                list_id="campaign_camp_2",
            )
            cached_first = self.module.cached_list(
                runner=runner,
                cache=cache,
                account_id="act_1",
                entity_type="adset",
                command=["meta", "ads", "adset", "list", "--campaign_id", "camp_1"],
                env={},
                refresh=False,
                list_id="campaign_camp_1",
            )

        self.assertEqual(first[0]["id"], "camp_1")
        self.assertEqual(second[0]["id"], "camp_2")
        self.assertEqual(cached_first[0]["id"], "camp_1")
        self.assertEqual(runner.calls, 2)

    def test_detects_level_support(self) -> None:
        self.assertTrue(
            self.module.detect_level_support(FakeRunner(level_supported=True))
        )
        self.assertFalse(
            self.module.detect_level_support(FakeRunner(level_supported=False))
        )

    def test_per_entity_insight_fallback_attaches_entity_id(self) -> None:
        rows = self.module.get_insights(
            runner=FakeRunner(level_supported=False),
            account_id="act_1",
            since=datetime(2026, 4, 6, tzinfo=UTC).date(),
            until=datetime(2026, 5, 5, tzinfo=UTC).date(),
            level="ad",
            level_supported=False,
            entities=[{"id": "ad_1"}],
        )

        self.assertEqual(rows[0]["ad_id"], "ad_1")

    def test_reconciliation_warns_when_ad_level_is_short(self) -> None:
        warnings = self.module.reconcile(
            account_rows=[
                {
                    "account_id": "act_1",
                    "actions": [{"action_type": "purchase", "value": "6"}],
                }
            ],
            campaign_rows=[
                {
                    "account_id": "act_1",
                    "actions": [{"action_type": "purchase", "value": "6"}],
                }
            ],
            adset_rows=[
                {
                    "account_id": "act_1",
                    "actions": [{"action_type": "purchase", "value": "6"}],
                }
            ],
            ad_rows=[
                {
                    "account_id": "act_1",
                    "actions": [{"action_type": "purchase", "value": "4"}],
                }
            ],
        )

        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["gap"], 2)
        self.assertIn("not traceable", warnings[0]["message"])

    def test_extracts_creative_fields(self) -> None:
        creative = self.module.extract_creative_fields(
            {
                "id": "creative_1",
                "thumbnail_url": "https://example.test/t.jpg",
                "object_story_spec": {
                    "link_data": {
                        "image_hash": "hash_1",
                        "message": "Primary",
                        "name": "Headline",
                        "link": "https://example.test",
                        "call_to_action": {"type": "SHOP_NOW"},
                    }
                },
            }
        )

        self.assertEqual(creative["thumbnail_url"], "https://example.test/t.jpg")
        self.assertEqual(creative["image_hash"], "hash_1")
        self.assertEqual(creative["cta"], "SHOP_NOW")
        self.assertEqual(creative["primary_text"], "Primary")

    def test_ua_creative_audit_metrics(self) -> None:
        report = self.module.summarize_ua_creative_audit(
            ads=[{"id": "ad_1", "creative": {"id": "creative_1"}}],
            creatives=[{"id": "creative_1", "creative_visual_family": "image_hash:hash_1"}],
            ad_insights=[
                {
                    "account_id": "act_1",
                    "ad_id": "ad_1",
                    "spend": "100",
                    "impressions": "1000",
                    "actions": [
                        {"action_type": "purchase", "value": "4"},
                        {"action_type": "initiate_checkout", "value": "7"},
                        {"action_type": "complete_registration", "value": "10"},
                    ],
                    "action_values": [{"action_type": "purchase", "value": "200"}],
                    "video_p100_watched_actions": [
                        {"action_type": "video_view", "value": "250"}
                    ],
                }
            ],
        )

        row = report["ranked_by_purchases"][0]
        self.assertEqual(row["purchases"], 4)
        self.assertEqual(row["cpa"], 25)
        self.assertEqual(row["roas"], 2)
        self.assertEqual(row["checkout_without_purchase"], 3)
        self.assertEqual(row["registration_to_purchase_gap"], 6)
        self.assertEqual(row["video_completion_rate"], 0.25)

    def test_run_audit_emits_report_shape_and_cache_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = self.module.parse_args(
                [
                    "--accounts",
                    "act_1",
                    "--since",
                    "2026-04-06",
                    "--until",
                    "2026-05-05",
                    "--cache-dir",
                    str(Path(tmp) / "cache"),
                    "--assets-dir",
                    str(Path(tmp) / "assets"),
                    "--no-download-assets",
                ]
            )

            report = self.module.run_audit(args, runner=FakeRunner())

        self.assertEqual(report["metadata"]["since"], "2026-04-06")
        self.assertEqual(report["metadata"]["until"], "2026-05-05")
        self.assertTrue(report["metadata"]["insights_level_supported"])
        self.assertEqual(len(report["tables"]["campaigns"]), 1)
        self.assertEqual(len(report["tables"]["creatives"]), 1)
        self.assertEqual(report["tables"]["creatives"][0]["cta"], "SHOP_NOW")
        self.assertGreater(report["metadata"]["cache"]["writes"], 0)
        self.assertIn("ua-creative-audit", report["preset_reports"])
        self.assertTrue(
            any(warning["type"] == "reconciliation_gap" for warning in report["warnings"])
        )

    def test_main_redacts_errors(self) -> None:
        bad = "access_token=EAAabcdefghi12345 app_secret=secret"
        with (
            mock.patch.object(self.module, "parse_args", side_effect=ValueError(bad)),
            contextlib.redirect_stderr(io.StringIO()) as stderr,
        ):
            code = self.module.main(["--accounts", "act_1"])

        self.assertEqual(code, 1)
        self.assertNotIn("=secret", stderr.getvalue())
        self.assertIn("[REDACTED]", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
