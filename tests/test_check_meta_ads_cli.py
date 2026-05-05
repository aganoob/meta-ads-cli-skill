from __future__ import annotations

import contextlib
import importlib.util
import io
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "meta-ads-cli" / "scripts" / "check_meta_ads_cli.py"


def load_module():
    spec = importlib.util.spec_from_file_location("check_meta_ads_cli", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class CheckMetaAdsCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()

    def run_main(self) -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = self.module.main()
        return code, output.getvalue()

    def test_fails_when_python_version_is_too_old(self) -> None:
        with (
            mock.patch.object(self.module.sys, "version_info", (3, 11, 9)),
            mock.patch.object(self.module.shutil, "which", return_value="/usr/bin/meta"),
            mock.patch.object(
                self.module,
                "run",
                side_effect=[(0, "meta help"), (0, "meta ads help")],
            ),
        ):
            code, output = self.run_main()

        self.assertEqual(code, 1)
        self.assertIn("python_check: FAIL", output)
        self.assertIn("meta_ads_help: OK", output)

    def test_fails_when_meta_binary_is_missing(self) -> None:
        with mock.patch.object(self.module.shutil, "which", return_value=None):
            code, output = self.run_main()

        expected = 1 if sys.version_info >= (3, 12) else 1
        self.assertEqual(code, expected)
        self.assertIn("meta_binary: FAIL", output)

    def test_succeeds_when_meta_help_commands_work(self) -> None:
        with (
            mock.patch.object(self.module.sys, "version_info", (3, 12, 0)),
            mock.patch.object(self.module.shutil, "which", return_value="/usr/bin/meta"),
            mock.patch.object(
                self.module,
                "run",
                side_effect=[(0, "Meta CLI\nusage"), (0, "Meta Ads CLI\nusage")],
            ),
        ):
            code, output = self.run_main()

        self.assertEqual(code, 0)
        self.assertIn("python_check: OK", output)
        self.assertIn("meta_help: OK - Meta CLI", output)
        self.assertIn("meta_ads_help: OK - Meta Ads CLI", output)

    def test_returns_meta_help_failure_code(self) -> None:
        with (
            mock.patch.object(self.module.sys, "version_info", (3, 12, 0)),
            mock.patch.object(self.module.shutil, "which", return_value="/usr/bin/meta"),
            mock.patch.object(self.module, "run", return_value=(3, "auth failed")),
        ):
            code, output = self.run_main()

        self.assertEqual(code, 3)
        self.assertIn("meta_help: FAIL - exit code 3", output)
        self.assertIn("auth failed", output)

    def test_run_handles_missing_command(self) -> None:
        with mock.patch.object(
            self.module.subprocess,
            "run",
            side_effect=FileNotFoundError,
        ):
            code, output = self.module.run(["missing"])

        self.assertEqual(code, 127)
        self.assertEqual(output, "command not found")

    def test_run_handles_timeout(self) -> None:
        with mock.patch.object(
            self.module.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["meta"], timeout=20),
        ):
            code, output = self.module.run(["meta"])

        self.assertEqual(code, 124)
        self.assertEqual(output, "command timed out")


if __name__ == "__main__":
    unittest.main()
