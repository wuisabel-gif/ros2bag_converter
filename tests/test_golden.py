# SPDX-License-Identifier: Apache-2.0
"""Golden-snapshot test for cli/python.

Builds the deterministic sample bag, runs the Python CLI, and compares its
output against committed snapshots in tests/golden/. Catches accidental changes
to decoding or export formatting. Run: `python3 tests/test_golden.py`.
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GOLDEN = os.path.join(HERE, "golden")
PYCLI = os.path.join(ROOT, "cli", "python")

sys.path.insert(0, HERE)
import sample_bag  # noqa: E402


def run_cli(bag, *args):
    r = subprocess.run(
        [sys.executable, "-m", "ros2bag_converter.cli", *args, bag],
        cwd=PYCLI, capture_output=True, text=True,
    )
    return r.stdout


CASES = {
    "info.txt": ("info",),
    "all.json": ("-f", "json"),
    "all.csv": ("-f", "csv"),
    "imu.csv": ("-f", "csv", "-t", "/imu"),
    "tf.csv": ("-f", "csv", "-t", "/tf"),
    "widget.csv": ("-f", "csv", "-t", "/widget"),
}


def main():
    with tempfile.TemporaryDirectory() as d:
        bag = sample_bag.build(os.path.join(d, "sample.db3"))
        failures = []
        for name, args in CASES.items():
            got = run_cli(bag, *args)
            with open(os.path.join(GOLDEN, name), encoding="utf-8") as fh:
                want = fh.read()
            if got == want:
                print(f"  ✓ {name}")
            else:
                failures.append(name)
                print(f"  ✗ {name}  (output differs from golden)")

        # Cross-format: MCAP must decode to the same output as .db3, except the
        # storage line in `info` (sqlite3 vs mcap).
        mcap = sample_bag.build_mcap(os.path.join(d, "sample.mcap"))
        for name, args in CASES.items():
            db3_out, mcap_out = run_cli(bag, *args), run_cli(mcap, *args)
            if name == "info.txt":
                db3_out = db3_out.replace("sqlite3", "")
                mcap_out = mcap_out.replace("mcap", "")
            if db3_out == mcap_out:
                print(f"  ✓ mcap==db3: {name}")
            else:
                failures.append(f"mcap=={name}")
                print(f"  ✗ mcap==db3: {name}  (MCAP output differs from .db3)")

        if failures:
            print(f"\nFAILED: {len(failures)} mismatch(es): {', '.join(failures)}")
            print("If the change is intentional, regenerate tests/golden/ and review the diff.")
            return 1
        print(f"\n{len(CASES) * 2} checks passed (golden + cross-format).")
        return 0


if __name__ == "__main__":
    sys.exit(main())
