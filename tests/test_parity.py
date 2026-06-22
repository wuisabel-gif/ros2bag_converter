# SPDX-License-Identifier: Apache-2.0
"""Drift guard: the skill's single-file engine must match cli/python exactly.

The skill bundles a consolidated copy of the cli/python decoder for portability.
This test runs both implementations over the same sample bag and asserts byte-
identical output, so the two cannot silently diverge. Run:
`python3 tests/test_parity.py`.
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PYCLI = os.path.join(ROOT, "cli", "python")
SKILL = os.path.join(ROOT, "skills", "ros2bag-converter", "scripts", "ros2bag_convert.py")

sys.path.insert(0, HERE)
import sample_bag  # noqa: E402


def run_pkg(bag, *args):
    return subprocess.run(
        [sys.executable, "-m", "ros2bag_converter.cli", *args, bag],
        cwd=PYCLI, capture_output=True, text=True,
    ).stdout


def run_skill(bag, *args):
    return subprocess.run(
        [sys.executable, SKILL, *args, bag],
        capture_output=True, text=True,
    ).stdout


INVOCATIONS = [
    ("info",),
    ("-f", "json"),
    ("-f", "csv"),
    ("-f", "csv", "-t", "/imu"),
    ("-f", "csv", "-t", "/widget"),
]


def main():
    with tempfile.TemporaryDirectory() as d:
        bags = {
            "db3": sample_bag.build(os.path.join(d, "sample.db3")),
            "mcap": sample_bag.build_mcap(os.path.join(d, "sample.mcap")),
        }
        failures = []
        for kind, bag in bags.items():
            for args in INVOCATIONS:
                label = f"{kind}: {' '.join(args)}"
                pkg, skill = run_pkg(bag, *args), run_skill(bag, *args)
                if pkg == skill:
                    print(f"  ✓ parity: {label}")
                else:
                    failures.append(label)
                    print(f"  ✗ parity: {label}  (skill engine != cli/python)")
        if failures:
            print("\nFAILED: skill engine has drifted from cli/python.")
            print("Re-sync skills/ros2bag-converter/scripts/ros2bag_convert.py with cli/python.")
            return 1
        print(f"\n{len(INVOCATIONS) * len(bags)} parity checks passed.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
