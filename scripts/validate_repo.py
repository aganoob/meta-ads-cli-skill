#!/usr/bin/env python3
"""Validate repository structure for the Meta Ads CLI skill."""

from __future__ import annotations

import py_compile
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = [
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "Makefile",
    "meta-ads-cli/SKILL.md",
    "meta-ads-cli/agents/openai.yaml",
    "meta-ads-cli/references/command-patterns.md",
    "meta-ads-cli/scripts/check_meta_ads_cli.py",
    "meta-ads-cli/scripts/meta_ads_audit.py",
    ".github/workflows/ci.yml",
    ".github/pull_request_template.md",
]

PYTHON_FILES = [
    "scripts/validate_repo.py",
    "meta-ads-cli/scripts/check_meta_ads_cli.py",
    "meta-ads-cli/scripts/meta_ads_audit.py",
    "tests/test_check_meta_ads_cli.py",
    "tests/test_meta_ads_audit.py",
]


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def read_required(path: str) -> str:
    file_path = ROOT / path
    if not file_path.is_file():
        fail(f"missing required file: {path}")
    content = file_path.read_text(encoding="utf-8")
    if not content.strip():
        fail(f"required file is empty: {path}")
    return content


def validate_skill_markdown() -> None:
    skill = read_required("meta-ads-cli/SKILL.md")
    reference = read_required("meta-ads-cli/references/command-patterns.md")

    if not skill.startswith("---\n"):
        fail("meta-ads-cli/SKILL.md must start with front matter")
    for needle in ["name: meta-ads-cli", "description:", "# Meta Ads CLI"]:
        if needle not in skill:
            fail(f"meta-ads-cli/SKILL.md missing {needle!r}")
    for needle in ["## Operating Model", "## First Checks", "## Workflow"]:
        if needle not in skill:
            fail(f"meta-ads-cli/SKILL.md missing section {needle!r}")
    if "Plan/Preview/Apply" not in reference:
        fail("command-patterns.md must include the Plan/Preview/Apply pattern")


def validate_agent_yaml_shape() -> None:
    content = read_required("meta-ads-cli/agents/openai.yaml")
    required_patterns = [
        r"^interface:\s*$",
        r"^\s{2}display_name:\s+.+$",
        r"^\s{2}short_description:\s+.+$",
        r"^\s{2}default_prompt:\s+\|$",
        r"Safety rules",
        r"Current docs",
    ]
    for pattern in required_patterns:
        if not re.search(pattern, content, flags=re.MULTILINE):
            fail(f"openai.yaml missing expected YAML shape: {pattern}")


def validate_python_syntax() -> None:
    for path in PYTHON_FILES:
        file_path = ROOT / path
        if not file_path.is_file():
            fail(f"missing Python file: {path}")
        try:
            py_compile.compile(str(file_path), doraise=True)
        except py_compile.PyCompileError as error:
            fail(f"Python syntax error in {path}: {error.msg}")


def main() -> int:
    for path in REQUIRED_FILES:
        read_required(path)
    validate_skill_markdown()
    validate_agent_yaml_shape()
    validate_python_syntax()
    print("Repository validation OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
