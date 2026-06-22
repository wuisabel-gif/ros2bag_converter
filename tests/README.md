# Tests

Cross-implementation tests for the decoder, run in [CI](../.github/workflows/ci.yml).

| File | Purpose |
|---|---|
| `sample_bag.py` | Builds a deterministic synthetic rosbag2 `.db3` (String, Imu with covariance arrays, TFMessage, and a **custom type via `message_definitions`**). Importable + runnable. |
| `test_golden.py` | Runs `cli/python` over the sample bag and compares to committed snapshots in `golden/`. Catches changes to decoding or export formatting. |
| `test_parity.py` | Drift guard — asserts the skill's single-file engine (`skills/ros2bag-converter/scripts/ros2bag_convert.py`) produces byte-identical output to `cli/python`. |
| `golden/` | Snapshot outputs (`info.txt`, `all.json`, `*.csv`). |

```bash
python3 tests/test_golden.py
python3 tests/test_parity.py
```

The Node CLI has its own smoke test: `cd cli/node && npm test`.

## Updating golden files

If you intentionally change decoding/formatting, regenerate and review the diff:

```bash
python3 tests/sample_bag.py /tmp/s.db3
cd cli/python
python3 -m ros2bag_converter.cli info /tmp/s.db3            > ../../tests/golden/info.txt
python3 -m ros2bag_converter.cli /tmp/s.db3 -f json         > ../../tests/golden/all.json
python3 -m ros2bag_converter.cli /tmp/s.db3 -f csv          > ../../tests/golden/all.csv
python3 -m ros2bag_converter.cli /tmp/s.db3 -f csv -t /imu  > ../../tests/golden/imu.csv
python3 -m ros2bag_converter.cli /tmp/s.db3 -f csv -t /tf   > ../../tests/golden/tf.csv
python3 -m ros2bag_converter.cli /tmp/s.db3 -f csv -t /widget > ../../tests/golden/widget.csv
```
