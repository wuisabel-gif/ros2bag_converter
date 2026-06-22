#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""ros2bag_convert — self-contained ROS 2 .db3 bag inspector / exporter.

Single-file, standard-library-only build of the `ros2bag_converter` package
(see cli/python in https://github.com/wuisabel-gif/ros2bag_converter). Decodes
CDR-serialized rosbag2 messages and exports topics to CSV / JSON — no ROS 2
install, no third-party dependencies.

Usage:
    python3 ros2bag_convert.py <bag.db3> [options]   # export (default)
    python3 ros2bag_convert.py info <bag.db3>         # summary
    python3 ros2bag_convert.py list <bag.db3>         # topics + counts

Options:
    -f, --format {csv,json}   output format (default: csv)
    -o, --output FILE         write to file (default: stdout)
    -t, --topic NAME          include topic; repeatable (default: all)
    -m, --metadata FILE       metadata.yaml for storage/distro info
        --max-rows N          per-topic row cap (default: 500000)
    -h, --help                show this help
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import struct
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

# ===========================================================================
# Schema registry + .msg parser
# ===========================================================================
PRIM = {
    "bool", "byte", "char", "int8", "uint8", "int16", "uint16",
    "int32", "uint32", "int64", "uint64", "float32", "float64", "string", "wstring",
}
PRIM_SIZE = {
    "bool": 1, "byte": 1, "char": 1, "int8": 1, "uint8": 1, "int16": 2, "uint16": 2,
    "int32": 4, "uint32": 4, "int64": 8, "uint64": 8, "float32": 4, "float64": 8,
}
registry: dict[str, list[dict]] = {}
_ARRAY_RE = re.compile(r"^(.+?)\[(\d*)\]$")


def norm(n: str) -> str:
    return n.replace("/msg/", "/").strip()


def parse_msg_text(type_name: str, text: str) -> None:
    fields = []
    for raw in text.split("\n"):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        ftype, name = parts[0], parts[1]
        if "=" in name:
            continue
        is_array, array_len = False, None
        m = _ARRAY_RE.match(ftype)
        if m:
            is_array = True
            ftype = m.group(1)
            array_len = int(m.group(2)) if m.group(2) else None
        ftype = re.sub(r"<=\d+", "", ftype).replace("/msg/", "/")
        fields.append({"name": name, "type": ftype, "is_array": is_array, "array_len": array_len})
    registry[norm(type_name)] = fields


def register_encoded_definition(root_type: str, encoded: str) -> None:
    blocks = re.split(r"^=+\s*$", encoded, flags=re.MULTILINE)
    if blocks:
        parse_msg_text(root_type, blocks[0])
    for block in blocks[1:]:
        mm = re.match(r"^MSG:\s*(\S+)\s*\n([\s\S]*)$", block.strip())
        if mm:
            parse_msg_text(mm.group(1), mm.group(2))


def resolve_type(t: str) -> str:
    t = norm(t)
    if t in PRIM or t in registry:
        return t
    for k in registry:
        if k.endswith("/" + t):
            return k
    if t == "Header":
        return "std_msgs/Header"
    return t


BUILTIN = {
    "builtin_interfaces/Time": "int32 sec\nuint32 nanosec",
    "builtin_interfaces/Duration": "int32 sec\nuint32 nanosec",
    "std_msgs/Header": "builtin_interfaces/Time stamp\nstring frame_id",
    "std_msgs/String": "string data",
    "std_msgs/Bool": "bool data",
    "std_msgs/Empty": "",
    "std_msgs/ColorRGBA": "float32 r\nfloat32 g\nfloat32 b\nfloat32 a",
    "geometry_msgs/Vector3": "float64 x\nfloat64 y\nfloat64 z",
    "geometry_msgs/Point": "float64 x\nfloat64 y\nfloat64 z",
    "geometry_msgs/Point32": "float32 x\nfloat32 y\nfloat32 z",
    "geometry_msgs/Quaternion": "float64 x\nfloat64 y\nfloat64 z\nfloat64 w",
    "geometry_msgs/Pose": "geometry_msgs/Point position\ngeometry_msgs/Quaternion orientation",
    "geometry_msgs/PoseWithCovariance": "geometry_msgs/Pose pose\nfloat64[36] covariance",
    "geometry_msgs/PoseStamped": "std_msgs/Header header\ngeometry_msgs/Pose pose",
    "geometry_msgs/PoseWithCovarianceStamped": "std_msgs/Header header\ngeometry_msgs/PoseWithCovariance pose",
    "geometry_msgs/Twist": "geometry_msgs/Vector3 linear\ngeometry_msgs/Vector3 angular",
    "geometry_msgs/TwistWithCovariance": "geometry_msgs/Twist twist\nfloat64[36] covariance",
    "geometry_msgs/TwistStamped": "std_msgs/Header header\ngeometry_msgs/Twist twist",
    "geometry_msgs/Accel": "geometry_msgs/Vector3 linear\ngeometry_msgs/Vector3 angular",
    "geometry_msgs/Wrench": "geometry_msgs/Vector3 force\ngeometry_msgs/Vector3 torque",
    "geometry_msgs/Transform": "geometry_msgs/Vector3 translation\ngeometry_msgs/Quaternion rotation",
    "geometry_msgs/TransformStamped": "std_msgs/Header header\nstring child_frame_id\ngeometry_msgs/Transform transform",
    "tf2_msgs/TFMessage": "geometry_msgs/TransformStamped[] transforms",
    "nav_msgs/Odometry": "std_msgs/Header header\nstring child_frame_id\ngeometry_msgs/PoseWithCovariance pose\ngeometry_msgs/TwistWithCovariance twist",
    "nav_msgs/Path": "std_msgs/Header header\ngeometry_msgs/PoseStamped[] poses",
    "sensor_msgs/Imu": "std_msgs/Header header\ngeometry_msgs/Quaternion orientation\nfloat64[9] orientation_covariance\ngeometry_msgs/Vector3 angular_velocity\nfloat64[9] angular_velocity_covariance\ngeometry_msgs/Vector3 linear_acceleration\nfloat64[9] linear_acceleration_covariance",
    "sensor_msgs/Range": "std_msgs/Header header\nuint8 radiation_type\nfloat32 field_of_view\nfloat32 min_range\nfloat32 max_range\nfloat32 range",
    "sensor_msgs/Temperature": "std_msgs/Header header\nfloat64 temperature\nfloat64 variance",
    "sensor_msgs/FluidPressure": "std_msgs/Header header\nfloat64 fluid_pressure\nfloat64 variance",
    "sensor_msgs/RelativeHumidity": "std_msgs/Header header\nfloat64 relative_humidity\nfloat64 variance",
    "sensor_msgs/Illuminance": "std_msgs/Header header\nfloat64 illuminance\nfloat64 variance",
    "sensor_msgs/MagneticField": "std_msgs/Header header\ngeometry_msgs/Vector3 magnetic_field\nfloat64[9] magnetic_field_covariance",
    "sensor_msgs/NavSatStatus": "int8 status\nuint16 service",
    "sensor_msgs/NavSatFix": "std_msgs/Header header\nsensor_msgs/NavSatStatus status\nfloat64 latitude\nfloat64 longitude\nfloat64 altitude\nfloat64[9] position_covariance\nuint8 position_covariance_type",
    "sensor_msgs/PointField": "string name\nuint32 offset\nuint8 datatype\nuint32 count",
    "sensor_msgs/PointCloud2": "std_msgs/Header header\nuint32 height\nuint32 width\nsensor_msgs/PointField[] fields\nbool is_bigendian\nuint32 point_step\nuint32 row_step\nuint8[] data\nbool is_dense",
    "sensor_msgs/Image": "std_msgs/Header header\nuint32 height\nuint32 width\nstring encoding\nuint8 is_bigendian\nuint32 step\nuint8[] data",
    "sensor_msgs/CompressedImage": "std_msgs/Header header\nstring format\nuint8[] data",
    "sensor_msgs/LaserScan": "std_msgs/Header header\nfloat32 angle_min\nfloat32 angle_max\nfloat32 angle_increment\nfloat32 time_increment\nfloat32 scan_time\nfloat32 range_min\nfloat32 range_max\nfloat32[] ranges\nfloat32[] intensities",
    "sensor_msgs/JointState": "std_msgs/Header header\nstring[] name\nfloat64[] position\nfloat64[] velocity\nfloat64[] effort",
    "sensor_msgs/Joy": "std_msgs/Header header\nfloat32[] axes\nint32[] buttons",
    "sensor_msgs/BatteryState": "std_msgs/Header header\nfloat32 voltage\nfloat32 temperature\nfloat32 current\nfloat32 charge\nfloat32 capacity\nfloat32 design_capacity\nfloat32 percentage\nuint8 power_supply_status\nuint8 power_supply_health\nuint8 power_supply_technology\nbool present\nfloat32[] cell_voltage\nfloat32[] cell_temperature\nstring location\nstring serial_number",
}
for _k, _v in BUILTIN.items():
    parse_msg_text(_k, _v)
for _k, _p in {
    "Float32": "float32", "Float64": "float64", "Int8": "int8", "Int16": "int16",
    "Int32": "int32", "Int64": "int64", "UInt8": "uint8", "UInt16": "uint16",
    "UInt32": "uint32", "UInt64": "uint64", "Byte": "byte", "Char": "char",
}.items():
    parse_msg_text("std_msgs/" + _k, _p + " data")

# ===========================================================================
# CDR reader — ROS 2 wire format
# ===========================================================================
BYTE_ARR_CAP = 1024
PRIM_ARR_CAP = 8192


class CDR:
    def __init__(self, data: bytes):
        self.data = data
        self.le = (data[1] & 1) == 1 if len(data) > 1 else True
        self.origin = 4
        self.off = 4

    def align(self, n: int) -> None:
        rel = (self.off - self.origin) % n
        if rel:
            self.off += n - rel

    def _u(self, fmt: str, size: int, align: int):
        if align > 1:
            self.align(align)
        v = struct.unpack_from(("<" if self.le else ">") + fmt, self.data, self.off)[0]
        self.off += size
        return v

    def r_byte(self):
        v = self.data[self.off]; self.off += 1; return v

    def r_i8(self): return self._u("b", 1, 1)
    def r_u16(self): return self._u("H", 2, 2)
    def r_i16(self): return self._u("h", 2, 2)
    def r_u32(self): return self._u("I", 4, 4)
    def r_i32(self): return self._u("i", 4, 4)
    def r_f32(self): return self._u("f", 4, 4)
    def r_f64(self): return self._u("d", 8, 8)
    def r_i64(self): return self._u("q", 8, 8)
    def r_u64(self): return self._u("Q", 8, 8)

    def r_str(self):
        self.align(4)
        n = struct.unpack_from(("<" if self.le else ">") + "I", self.data, self.off)[0]
        self.off += 4
        if n == 0:
            return ""
        raw = self.data[self.off:self.off + n]
        self.off += n
        if len(raw) and raw[-1] == 0:
            raw = raw[:-1]
        return raw.decode("utf-8", "replace")


_SCALAR = {
    "byte": "r_byte", "uint8": "r_byte", "char": "r_byte",
    "int8": "r_i8", "int16": "r_i16", "uint16": "r_u16",
    "int32": "r_i32", "uint32": "r_u32", "int64": "r_i64", "uint64": "r_u64",
    "float32": "r_f32", "float64": "r_f64",
}


def read_scalar(cdr: CDR, type_: str):
    if type_ == "bool":
        return cdr.r_byte() != 0
    if type_ in ("string", "wstring"):
        return cdr.r_str()
    fn = _SCALAR.get(type_)
    if fn:
        return getattr(cdr, fn)()
    return read_type(cdr, resolve_type(type_))


def read_field(cdr: CDR, f: dict):
    if not f["is_array"]:
        return read_scalar(cdr, f["type"])
    length = f["array_len"]
    if length is None:
        cdr.align(4)
        length = cdr.r_u32()
    t = norm(f["type"])
    if t in PRIM and t not in ("string", "wstring"):
        sz = PRIM_SIZE[t]
        is_byte = t in ("uint8", "byte", "char", "int8")
        summarize = length > BYTE_ARR_CAP if is_byte else length > PRIM_ARR_CAP
        if summarize:
            if sz > 1:
                cdr.align(sz)
            cdr.off += length * sz
            return {"__array__": t, "length": length}
        return [read_scalar(cdr, t) for _ in range(length)]
    return [read_scalar(cdr, t) for _ in range(length)]


def read_type(cdr: CDR, type_name: str) -> dict:
    fields = registry.get(type_name)
    if fields is None:
        raise ValueError("no schema for " + type_name)
    return {f["name"]: read_field(cdr, f) for f in fields}


def decode_message(type_name: str, data: bytes) -> dict:
    return read_type(CDR(data), norm(type_name))


def is_decodable(type_name) -> bool:
    return norm(type_name or "") in registry


# ===========================================================================
# CSV flattening
# ===========================================================================
def flatten(obj: dict, prefix: str, out: dict) -> None:
    for k, v in obj.items():
        key = f"{prefix}.{k}" if prefix else k
        if v is None:
            out[key] = ""
        elif isinstance(v, list):
            if v and isinstance(v[0], (dict, list)):
                out[key] = json.dumps(v, separators=(",", ":"))
            elif len(v) > 64:
                out[key] = f"[{len(v)} values]"
            else:
                for i, el in enumerate(v):
                    if isinstance(el, dict):
                        flatten(el, f"{key}.{i}", out)
                    else:
                        out[f"{key}.{i}"] = el
        elif isinstance(v, dict):
            if "__array__" in v:
                out[key] = f"[{v['length']} × {v['__array__']}]"
            else:
                flatten(v, key, out)
        else:
            out[key] = v


def csv_cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        s = "true" if v else "false"
    else:
        s = str(v)
    if any(c in s for c in '",\n\r'):
        s = '"' + s.replace('"', '""') + '"'
    return s


# ===========================================================================
# rosbag2 SQLite (.db3) reader
# ===========================================================================
@dataclass
class Topic:
    id: int
    name: str
    type: str
    fmt: str
    cnt: int
    tmin: "int | None"
    tmax: "int | None"
    decodable: bool


@dataclass
class Bag:
    conn: sqlite3.Connection
    topics: list = field(default_factory=list)
    total: int = 0
    gmin: "int | None" = None
    gmax: "int | None" = None
    storage: str = "sqlite3"
    distro: str = ""

    def each_message(self, topic_id: int, max_rows: "int | None" = None):
        cur = self.conn.execute(
            "SELECT timestamp, data FROM messages WHERE topic_id=? ORDER BY timestamp",
            (topic_id,),
        )
        n = 0
        self._truncated = False
        for ts, data in cur:
            if max_rows is not None and n >= max_rows:
                self._truncated = True
                break
            yield ts, bytes(data)
            n += 1

    def close(self):
        self.conn.close()


def _table_exists(conn, name) -> bool:
    r = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return r is not None


def open_bag(db3_path: str, metadata_path: "str | None" = None) -> Bag:
    if not os.path.exists(db3_path):
        raise FileNotFoundError(f"file not found: {db3_path}")
    try:
        conn = sqlite3.connect(f"file:{db3_path}?mode=ro", uri=True)
        conn.execute("SELECT name FROM sqlite_master LIMIT 1")
    except sqlite3.DatabaseError as e:
        raise ValueError(
            f'Could not open "{db3_path}" as SQLite — it may be corrupted or truncated. ({e})'
        )
    if not _table_exists(conn, "topics") or not _table_exists(conn, "messages"):
        raise ValueError('Not a rosbag2 SQLite bag — missing the "topics" / "messages" tables.')

    if _table_exists(conn, "message_definitions"):
        try:
            for tt, enc, definition in conn.execute(
                "SELECT topic_type, encoding, encoded_message_definition FROM message_definitions"
            ):
                if definition and (enc == "ros2msg" or enc is None):
                    try:
                        register_encoded_definition(norm(tt), definition)
                    except Exception:
                        pass
        except sqlite3.DatabaseError:
            pass

    bag = Bag(conn=conn)
    for tid, name, type_, fmt, cnt, tmin, tmax in conn.execute(
        """SELECT t.id, t.name, t.type, COALESCE(t.serialization_format,'cdr') fmt,
                  COUNT(m.id) cnt, MIN(m.timestamp) tmin, MAX(m.timestamp) tmax
           FROM topics t LEFT JOIN messages m ON m.topic_id=t.id
           GROUP BY t.id ORDER BY t.name"""
    ):
        type_ = type_ or "(unknown)"
        bag.topics.append(Topic(tid, name, type_, fmt, cnt, tmin, tmax, is_decodable(type_)))
        bag.total += cnt
        if cnt > 0:
            if bag.gmin is None or tmin < bag.gmin:
                bag.gmin = tmin
            if bag.gmax is None or tmax > bag.gmax:
                bag.gmax = tmax

    if metadata_path and os.path.exists(metadata_path):
        with open(metadata_path, "r", encoding="utf-8", errors="replace") as fh:
            meta = fh.read()
        sm = re.search(r"storage_identifier:\s*(\S+)", meta)
        if sm:
            bag.storage = sm.group(1)
        dm = re.search(r"ros_distro:\s*(\S+)", meta)
        if dm:
            bag.distro = dm.group(1)
    return bag


# ===========================================================================
# CLI
# ===========================================================================
HELP = __doc__


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
    errs = done = 0
    truncated = False
    try:
        if args.format == "json":
            out.write("[")
            first = True
            for t in sel:
                for ts, data in bag.each_message(t.id, args.max_rows):
                    try:
                        decoded = decode_message(t.type, data) if t.decodable else {"__raw_bytes__": len(data)}
                    except Exception as e:  # noqa: BLE001
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
        sys.stderr.write(f"ros2bag_convert: {e}\n")
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
        sys.stderr.write("ros2bag_convert: no .db3 bag path given\n")
        return 1

    try:
        bag = open_bag(bag_path, args.metadata)
    except (FileNotFoundError, ValueError) as e:
        sys.stderr.write(f"ros2bag_convert: {e}\n")
        return 1
    try:
        if command == "info":
            cmd_info(bag)
        elif command == "list":
            cmd_list(bag)
        else:
            cmd_convert(bag, args)
    except ValueError as e:
        sys.stderr.write(f"ros2bag_convert: {e}\n")
        return 1
    finally:
        bag.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
