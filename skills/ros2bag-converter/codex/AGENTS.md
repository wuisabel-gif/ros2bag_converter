# ROS 2 bag converter (for Codex / AGENTS.md-aware agents)

This project bundles a standard-library Python tool to inspect and export ROS 2
`rosbag2` bags — SQLite `.db3` and MCAP `.mcap` (auto-detected) — to CSV / JSON
without a ROS 2 install.

When the user asks to inspect, summarize, list topics from, or convert/export a
`.db3` / `.mcap` / `rosbag2` file, use:

    python3 skills/ros2bag-converter/scripts/ros2bag_convert.py <command> <bag.db3> [options]

Commands: `info` (summary), `list` (topics), or omit for export (default).
Options: `-f csv|json`, `-o FILE`, `-t TOPIC` (repeatable), `-m metadata.yaml`,
`--max-rows N`. Data goes to stdout (or `-o`); the status line goes to stderr.

> Copy this block into your repo's root `AGENTS.md` if you want Codex to discover
> the tool automatically when working inside the project.
