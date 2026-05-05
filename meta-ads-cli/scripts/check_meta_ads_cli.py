#!/usr/bin/env python3
"""Check whether the local environment can run Meta Ads CLI."""

from __future__ import annotations

import shutil
import subprocess
import sys


def run(command: list[str]) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
        )
    except FileNotFoundError:
        return 127, "command not found"
    except subprocess.TimeoutExpired:
        return 124, "command timed out"
    return completed.returncode, completed.stdout.strip()


def main() -> int:
    ok = True

    print(f"python: {sys.version.split()[0]}")
    if sys.version_info < (3, 12):
        print("python_check: FAIL - Meta Ads CLI requires Python 3.12+")
        ok = False
    else:
        print("python_check: OK")

    meta_path = shutil.which("meta")
    if not meta_path:
        print("meta_binary: FAIL - `meta` was not found on PATH")
        return 1

    print(f"meta_binary: {meta_path}")

    code, output = run(["meta", "--help"])
    if code != 0:
        print(f"meta_help: FAIL - exit code {code}")
        if output:
            print(output)
        return code

    first_line = output.splitlines()[0] if output else "(no output)"
    print(f"meta_help: OK - {first_line}")

    code, output = run(["meta", "ads", "--help"])
    if code != 0:
        print(f"meta_ads_help: FAIL - exit code {code}")
        if output:
            print(output)
        return code

    first_line = output.splitlines()[0] if output else "(no output)"
    print(f"meta_ads_help: OK - {first_line}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
