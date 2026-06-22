"""ros2bag-convert — inspect ROS 2 .db3 bags and export topics to CSV / JSON.

Same decoder as the browser app at
https://wuisabel-gif.github.io/ros2bag_converter/
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from . import bag as bagmod
from .decoder import csv_cell, decode_message, flatten

HELP = """ros2bag-convert — inspect & export ROS 2 .db3 bags (CSV / JSON)

USAGE
  ros2bag-convert <bag.db3> [options]      export (default command)
  ros2bag-convert info <bag.db3>           print a bag summary (like 'ros2 bag info')
  ros2bag-convert list <bag.db3>           list topics, types and message counts

OPTIONS
  -f, --format <csv|json>   output format (default: csv)
  -o, --output <file>       write to file (default: stdout)
  -t, --topic <name>        include this topic; repeatable (default: all topics)
  -m, --metadata <file>     metadata.yaml for storage/distro info
      --max-rows <n>        per-topic row cap (default: 500000)
  -h, --help                show this help

EXAMPLES
  ros2bag-convert info my_bag.db3
  ros2bag-convert my_bag.db3 -f csv -t /odom -o odom.csv
  ros2bag-convert my_bag.db3 -f json > all_topics.json
"""


class Args:
    def __init__(self):
        self.format = "csv"
        self.output = None
        self.topics = []
        self.metadata = None
        self.max_rows = 500000
        self.help = False
        self.positional = []


def parse_args(argv):
    a = Args()
    it = iter(range(len(argv)))
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("-h", "--help"):
            a.help = True
        elif arg in ("-f", "--format"):
            i += 1; a.format = argv[i].lower()
        elif arg in ("-o", "--output"):
            i += 1; a.output = argv[i]
        elif arg in ("-t", "--topic"):
            i += 1; a.topics.append(argv[i])
        elif arg in ("-m", "--metadata"):
            i += 1; a.metadata = argv[i]
        elif arg == "--max-rows":
            i += 1; a.max_rows = max(1, int(argv[i]))
        elif arg.startswith("-"):
            raise ValueError(f"unknown option: {arg}")
        else:
            a.positional.append(arg)
        i += 1
    return a


def _fmt_dur(a, b):
    if a is None or b is None:
        return "—"
    s = (b - a) / 1e9
    if s < 60:
        return f"{s:.2f} s"
    return f"{int(s // 60)}m {s % 60:.0f}s"


def _fmt_time(ns):
    if ns is None:
        return "—"
    try:
        dt = datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S.") + f"{dt.microsecond // 1000:03d} UTC"
    except (ValueError, OverflowError, OSError):
        return "—"


def _select_topics(all_topics, wanted):
    if not wanted:
        return [t for t in all_topics if t.cnt > 0]
    out = []
    for name in wanted:
        match = next((t for t in all_topics if t.name == name), None)
        if match is None:
            raise ValueError(f"topic not found in bag: {name}")
        out.append(match)
    return out


def cmd_info(bag):
    lines = [
        f"Messages:   {bag.total:,}",
        f"Duration:   {_fmt_dur(bag.gmin, bag.gmax)}",
        f"Start:      {_fmt_time(bag.gmin)}",
        f"End:        {_fmt_time(bag.gmax)}",
        f"Storage:    {bag.storage}" + (f"  ·  distro: {bag.distro}" if bag.distro else ""),
        f"Topics:     {len(bag.topics)}",
        "",
    ]
    for t in bag.topics:
        lines.append(f"  {t.name}")
        lines.append(f"    type: {t.type}   count: {t.cnt:,}   "
                     f"{'decodable' if t.decodable else 'raw bytes only'}")
    sys.stdout.write("\n".join(lines) + "\n")


def cmd_list(bag):
    for t in bag.topics:
        suffix = "" if t.decodable else "\t(raw)"
        sys.stdout.write(f"{t.cnt}\t{t.type}\t{t.name}{suffix}\n")


def cmd_convert(bag, args):
    sel = _select_topics(bag.topics, args.topics)
    if not sel:
        raise ValueError("no topics to export")
    out = open(args.output, "w", encoding="utf-8", newline="") if args.output else sys.stdout
    truncated = errs = done = 0
    truncated = False

    try:
        if args.format == "json":
            out.write("[")
            first = True
            for t in sel:
                for ts, data in bag.each_message(t.id, args.max_rows):
                    try:
                        decoded = decode_message(t.type, data) if t.decodable else {"__raw_bytes__": len(data)}
                    except Exception as e:  # noqa: BLE001 — flag, don't crash
                        decoded = {"__decode_error__": str(e), "__raw_bytes__": len(data)}
                        errs += 1
                    rec = {"timestamp": ts / 1e9, "topic": t.name, "type": t.type, "data": decoded}
                    out.write(("" if first else ",") + "\n  " + json.dumps(rec, separators=(",", ":")))
                    first = False
                    done += 1
                truncated = truncated or getattr(bag, "_truncated", False)
            out.write("\n]\n")
        else:
            multi = len(sel) > 1
            col_order = {}
            rows = []
            for t in sel:
                for ts, data in bag.each_message(t.id, args.max_rows):
                    f = {}
                    if t.decodable:
                        try:
                            flatten(decode_message(t.type, data), "", f)
                        except Exception as e:  # noqa: BLE001
                            f["decode_error"] = str(e)
                            errs += 1
                    else:
                        f["raw_bytes"] = len(data)
                    for k in f:
                        col_order.setdefault(k, 1)
                    rows.append((ts / 1e9, t.name, f))
                    done += 1
                truncated = truncated or getattr(bag, "_truncated", False)
            cols = list(col_order.keys())
            header = ["timestamp"] + (["topic"] if multi else []) + cols
            out.write(",".join(csv_cell(c) for c in header) + "\n")
            for ts, topic, f in rows:
                cells = [ts] + ([topic] if multi else []) + [f.get(c, "") for c in cols]
                out.write(",".join(csv_cell(c) for c in cells) + "\n")
    finally:
        if args.output:
            out.close()

    note = f"Exported {done:,} messages from {len(sel)} topic(s)."
    if truncated:
        note += f" Hit the {args.max_rows:,}-row cap on some topics; raise --max-rows to include all."
    if errs:
        note += f" {errs} message(s) failed to decode and were flagged in the output."
    sys.stderr.write(note + "\n")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        args = parse_args(argv)
    except (ValueError, IndexError) as e:
        sys.stderr.write(f"ros2bag-convert: {e}\n")
        return 1

    if args.help or not args.positional:
        sys.stdout.write(HELP)
        return 0

    command, bag_path = "convert", None
    if args.positional[0] in ("info", "list", "convert"):
        command = args.positional[0]
        bag_path = args.positional[1] if len(args.positional) > 1 else None
    else:
        bag_path = args.positional[0]

    if not bag_path:
        sys.stderr.write("ros2bag-convert: no .db3 bag path given\n")
        return 1

    try:
        bag = bagmod.open_bag(bag_path, args.metadata)
    except (FileNotFoundError, ValueError) as e:
        sys.stderr.write(f"ros2bag-convert: {e}\n")
        return 1

    try:
        if command == "info":
            cmd_info(bag)
        elif command == "list":
            cmd_list(bag)
        else:
            cmd_convert(bag, args)
    except ValueError as e:
        sys.stderr.write(f"ros2bag-convert: {e}\n")
        return 1
    finally:
        bag.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
