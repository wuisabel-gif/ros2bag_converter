# ros2bag-convert (Python)

Inspect ROS 2 `.db3` **and `.mcap`** bags and export topics to CSV / JSON from the
terminal (format auto-detected). Same decoder as the
[web app](https://wuisabel-gif.github.io/ros2bag_converter/).
**Standard library only** — no third-party dependencies, no ROS 2 install. (MCAP with
zstd/lz4 chunk compression needs the optional `zstandard`/`lz4` packages.)

## Install

```bash
pip install ./cli/python          # from a clone of the repo
# or, for development
pip install -e ./cli/python
```

## Use

```bash
ros2bag-convert <bag.db3> [options]   # export (default command)
ros2bag-convert info <bag.db3>        # summary
ros2bag-convert list <bag.db3>        # topics + counts
```

| Option | Meaning |
|---|---|
| `-f, --format {csv,json}` | output format (default `csv`) |
| `-o, --output FILE` | write to file (default stdout) |
| `-t, --topic NAME` | include topic; repeatable (default all) |
| `-m, --metadata FILE` | `metadata.yaml` for storage/distro info |
| `--max-rows N` | per-topic row cap (default 500000) |

```bash
ros2bag-convert my_bag.db3 -f csv -t /odom -o odom.csv
ros2bag-convert my_bag.db3 -f json > all.json
```

## Library API

```python
from ros2bag_converter import open_bag, decode_message, flatten

bag = open_bag("my_bag.db3")
t = next(x for x in bag.topics if x.name == "/odom")
for ts, data in bag.each_message(t.id):
    print(ts / 1e9, decode_message(t.type, data))
bag.close()
```

Requires Python ≥ 3.8.
