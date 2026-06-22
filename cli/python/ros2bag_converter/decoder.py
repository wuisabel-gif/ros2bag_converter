# SPDX-License-Identifier: Apache-2.0
"""ROS 2 message schema registry + .msg parser + CDR deserializer.

Faithful port of the decoder that powers the browser app (index.html) and the
Node CLI. Same wire format, same built-in schemas, same array-summarization
caps. Pure standard library — no third-party dependencies.
"""

from __future__ import annotations

import json
import re
import struct

PRIM = {
    "bool", "byte", "char", "int8", "uint8", "int16", "uint16",
    "int32", "uint32", "int64", "uint64", "float32", "float64", "string", "wstring",
}
PRIM_SIZE = {
    "bool": 1, "byte": 1, "char": 1, "int8": 1, "uint8": 1, "int16": 2, "uint16": 2,
    "int32": 4, "uint32": 4, "int64": 8, "uint64": 8, "float32": 4, "float64": 8,
}

# typeName -> list of {name, type, is_array, array_len}
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
        if "=" in name:  # constant definition, skip
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


# ---------------------------------------------------------------------------
# CDR reader — ROS 2 wire format
# ---------------------------------------------------------------------------
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
        v = self.data[self.off]
        self.off += 1
        return v

    def r_i8(self):
        return self._u("b", 1, 1)

    def r_u16(self):
        return self._u("H", 2, 2)

    def r_i16(self):
        return self._u("h", 2, 2)

    def r_u32(self):
        return self._u("I", 4, 4)

    def r_i32(self):
        return self._u("i", 4, 4)

    def r_f32(self):
        return self._u("f", 4, 4)

    def r_f64(self):
        return self._u("d", 8, 8)

    def r_i64(self):
        return self._u("q", 8, 8)

    def r_u64(self):
        return self._u("Q", 8, 8)

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


# ---------------------------------------------------------------------------
# CSV flattening — mirrors the browser export
# ---------------------------------------------------------------------------
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
