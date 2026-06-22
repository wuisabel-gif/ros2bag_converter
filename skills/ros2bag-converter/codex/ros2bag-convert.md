Decode and export the user's ROS 2 rosbag2 bag (SQLite `.db3` or MCAP `.mcap`,
auto-detected) using the bundled converter. It is a single standard-library
Python 3 script — no ROS 2, no `pip install`, no third-party dependencies.
(MCAP zstd/lz4 chunk compression needs the optional zstandard/lz4 packages.)

Script path (set at install time):

    {{SKILL_DIR}}/scripts/ros2bag_convert.py

Follow this process:

1. Locate the `.db3` file. A rosbag2 recording is usually a folder containing
   `<name>_0.db3` plus `metadata.yaml`; pass the `.db3` path, and add
   `-m <metadata.yaml>` when it exists.

2. Inspect before exporting:

       python3 {{SKILL_DIR}}/scripts/ros2bag_convert.py info <bag.db3> -m <metadata.yaml>
       python3 {{SKILL_DIR}}/scripts/ros2bag_convert.py list <bag.db3>

3. Export. Default command is export; default format is CSV.

       # CSV (nested fields flattened, e.g. pose.position.x)
       python3 {{SKILL_DIR}}/scripts/ros2bag_convert.py <bag.db3> -f csv -t /odom -o odom.csv

       # JSON (full nested structure)
       python3 {{SKILL_DIR}}/scripts/ros2bag_convert.py <bag.db3> -f json -o all.json

Options: `-f csv|json`, `-o FILE` (omit for stdout; status note goes to stderr),
`-t TOPIC` (repeatable; omit for all non-empty topics), `--max-rows N`.

Notes: custom message types decode automatically when the bag embeds a
`message_definitions` table (ROS 2 Iron+); large binary arrays (point cloud /
image `data`) are summarized; undecodable messages export as raw byte-length
placeholders instead of failing.

User request / arguments: $ARGUMENTS
