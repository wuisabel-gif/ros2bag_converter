---
name: ros2bag-converter
description: Inspect ROS 2 rosbag2 .db3 (SQLite) bag files and export their topics to CSV or JSON without a ROS 2 installation. Use when the user has a .db3 / rosbag2 file and wants a summary (topics, message counts, duration, start/end time), wants to list topics, or wants to convert/export messages to CSV or JSON. Decodes CDR-serialized messages including common sensor_msgs, geometry_msgs, nav_msgs, tf2_msgs and std_msgs types, plus custom message types embedded in the bag.
---

# ROS 2 Bag Converter

Decode and export ROS 2 `rosbag2` SQLite bags (`.db3`) without ROS 2 installed.
The engine is a single self-contained Python script (standard library only —
no `pip install`, no ROS) at `scripts/ros2bag_convert.py` relative to this skill.

## When to use

Trigger when the user references a `.db3`, `rosbag`, `rosbag2` file, or a folder
containing one alongside a `metadata.yaml`, and wants to:
- see a **summary** (topics, types, counts, duration) — like `ros2 bag info`;
- **list** topics; or
- **export** messages to **CSV** or **JSON**.

## Instructions

### Step 1 — Locate the bag
Find the `.db3` file. A rosbag2 recording is usually a folder containing
`<name>_0.db3` and `metadata.yaml`. Use the `.db3` path. Pass `metadata.yaml`
with `-m` when present (adds storage/distro info to the summary).

### Step 2 — Inspect first
Run the summary so you (and the user) understand the bag before exporting:

```bash
python3 scripts/ros2bag_convert.py info /path/to/bag.db3 -m /path/to/metadata.yaml
```

To get a terse, parseable topic list (`count<TAB>type<TAB>name`):

```bash
python3 scripts/ros2bag_convert.py list /path/to/bag.db3
```

Note which topics are marked `decodable` vs `raw bytes only`.

### Step 3 — Export
CSV (nested fields flattened into columns, e.g. `pose.position.x`):

```bash
python3 scripts/ros2bag_convert.py /path/to/bag.db3 -f csv -t /odom -o odom.csv
```

JSON (full nested structure preserved):

```bash
python3 scripts/ros2bag_convert.py /path/to/bag.db3 -f json -o all.json
```

- Default command is **export**; omit a subcommand and pass the bag path.
- Default format is **csv**. Use `-f json` for JSON.
- Pass `-t <topic>` one or more times to pick topics; omit to export **all**
  non-empty topics. With multiple topics, CSV gains a `topic` column and unions
  columns across topics.
- Without `-o`, data is written to **stdout** and the one-line status note goes
  to **stderr** — so `... -f csv > out.csv` always yields clean CSV.
- `--max-rows N` caps rows per topic (default 500000).

## Behaviour notes
- Large binary arrays (point-cloud / image `data`) are summarized, not dumped.
- Custom message types decode automatically if the bag embeds a
  `message_definitions` table (ROS 2 Iron and newer); otherwise built-in schemas
  for common messages apply.
- Undecodable/unknown messages export as raw byte-length placeholders rather
  than failing the whole export.

## Reference
Same decoder as the web app and CLIs at
https://github.com/wuisabel-gif/ros2bag_converter
