# Agent skills

Package the ROS 2 bag converter as an **agent skill** so Claude Code or Codex CLI
can inspect and export `.db3` rosbag2 files on request. The engine is a single
standard-library Python script — no ROS 2, no `pip install`.

```
ros2bag-converter/
├── SKILL.md                     # Claude Code skill manifest
├── scripts/ros2bag_convert.py   # self-contained engine (stdlib only)
├── codex/
│   ├── ros2bag-convert.md       # Codex custom prompt (→ /ros2bag-convert)
│   └── AGENTS.md                # snippet for project-level AGENTS.md discovery
└── install.sh                   # installs for Claude and/or Codex
```

## Install

```bash
skills/ros2bag-converter/install.sh         # both Claude + Codex
skills/ros2bag-converter/install.sh claude  # Claude Code only
skills/ros2bag-converter/install.sh codex   # Codex CLI only
```

### Claude Code
Copies the skill to `~/.claude/skills/ros2bag-converter/`. Claude Code
auto-discovers it; just ask something like *"summarize this rosbag"* or
*"convert my_bag.db3 to CSV"* and the **ros2bag-converter** skill triggers.

### Codex CLI
Codex's customization model is custom prompts, so the installer:
- copies the engine to `~/.codex/skills/ros2bag-converter/scripts/`, and
- writes `~/.codex/prompts/ros2bag-convert.md` (with the script path baked in).

Then in Codex run **`/ros2bag-convert <bag.db3> to csv`**. Alternatively, paste
the snippet from `codex/AGENTS.md` into your repo's root `AGENTS.md` so Codex
discovers the tool automatically while working in a project.

## Use directly (no agent)

The script also runs standalone:

```bash
python3 ros2bag-converter/scripts/ros2bag_convert.py info my_bag.db3
python3 ros2bag-converter/scripts/ros2bag_convert.py my_bag.db3 -f csv -t /odom -o odom.csv
```

The engine mirrors `cli/python` and the web app; see the repo
[README](../README.md) for details.
