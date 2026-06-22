# SPDX-License-Identifier: Apache-2.0
"""Build a deterministic synthetic rosbag2 .db3 fixture for tests.

Covers: a primitive (String), a nested message with fixed covariance arrays
(Imu), an array-of-nested-with-header (TFMessage), and a CUSTOM type decoded
via the bag's own message_definitions table (Iron+ path). Standard library only.
"""

from __future__ import annotations

import os
import sqlite3
import struct


class Enc:
    """Minimal little-endian CDR encoder, origin-relative alignment (origin=4)."""

    def __init__(self):
        self.b = bytearray([0, 1, 0, 0])  # CDR_LE encapsulation header
        self.o = 4

    def align(self, n):
        r = (len(self.b) - self.o) % n
        if r:
            self.b += bytes(n - r)

    def u8(self, v):
        self.b.append(v & 0xFF)

    def boolean(self, v):
        self.b.append(1 if v else 0)

    def i32(self, v):
        self.align(4); self.b += struct.pack("<i", v)

    def u32(self, v):
        self.align(4); self.b += struct.pack("<I", v)

    def f32(self, v):
        self.align(4); self.b += struct.pack("<f", v)

    def f64(self, v):
        self.align(8); self.b += struct.pack("<d", v)

    def string(self, s):
        e = s.encode("utf-8")
        self.u32(len(e) + 1)
        self.b += e
        self.b.append(0)

    def f64_fixed(self, arr):  # fixed-size array: no length prefix
        for x in arr:
            self.f64(x)

    def header(self, sec, nsec, frame):
        self.i32(sec); self.u32(nsec); self.string(frame)

    def bytes(self):
        return bytes(self.b)


def _string_msg(s):
    e = Enc(); e.string(s); return e.bytes()


def _imu_msg(sec, nsec):
    e = Enc()
    e.header(sec, nsec, "imu_link")
    e.f64_fixed([0.0, 0.0, 0.0, 1.0])          # orientation x,y,z,w
    e.f64_fixed([float(i) for i in range(9)])  # orientation_covariance
    e.f64_fixed([0.1, 0.2, 0.3])               # angular_velocity
    e.f64_fixed([0.0] * 9)                      # angular_velocity_covariance
    e.f64_fixed([9.8, 0.0, 0.0])               # linear_acceleration
    e.f64_fixed([0.0] * 9)                      # linear_acceleration_covariance
    return e.bytes()


def _tf_msg(sec, nsec):
    e = Enc()
    e.u32(1)  # transforms array length
    e.header(sec, nsec, "odom")
    e.string("base_link")                      # child_frame_id
    e.f64_fixed([1.0, 2.0, 0.0])               # transform.translation
    e.f64_fixed([0.0, 0.0, 0.0, 1.0])          # transform.rotation
    return e.bytes()


def _widget_msg(value, count, label):
    # custom my_pkg/msg/Widget: float64 value, int32 count, string label
    e = Enc()
    e.f64(value); e.i32(count); e.string(label)
    return e.bytes()


WIDGET_DEF = "float64 value\nint32 count\nstring label\n"

TOPICS = [
    (1, "/chatter", "std_msgs/msg/String"),
    (2, "/imu", "sensor_msgs/msg/Imu"),
    (3, "/tf", "tf2_msgs/msg/TFMessage"),
    (4, "/widget", "my_pkg/msg/Widget"),
]


def build(path: str) -> str:
    """Create a deterministic sample bag at `path`. Returns the path."""
    if os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE topics(id INTEGER PRIMARY KEY, name TEXT, type TEXT, serialization_format TEXT);
        CREATE TABLE messages(id INTEGER PRIMARY KEY, topic_id INTEGER, timestamp INTEGER, data BLOB);
        CREATE TABLE message_definitions(id INTEGER PRIMARY KEY, topic_type TEXT, encoding TEXT, encoded_message_definition TEXT);
        """
    )
    for tid, name, type_ in TOPICS:
        con.execute("INSERT INTO topics VALUES (?,?,?,?)", (tid, name, type_, "cdr"))
    con.execute(
        "INSERT INTO message_definitions VALUES (?,?,?,?)",
        (None, "my_pkg/msg/Widget", "ros2msg", WIDGET_DEF),
    )

    rows = []
    mid = 1
    def add(topic_id, ts, blob):
        nonlocal mid
        rows.append((mid, topic_id, ts, blob)); mid += 1

    add(1, 1_000_000_000, _string_msg("hello"))
    add(1, 1_500_000_000, _string_msg("world"))
    add(2, 1_100_000_000, _imu_msg(1, 100_000_000))
    add(3, 1_200_000_000, _tf_msg(1, 200_000_000))
    add(4, 1_300_000_000, _widget_msg(3.14, 7, "alpha"))
    add(4, 1_800_000_000, _widget_msg(-2.5, 0, "beta"))

    con.executemany("INSERT INTO messages VALUES (?,?,?,?)", rows)
    con.commit(); con.close()
    return path


MCAP_MAGIC = b"\x89MCAP0\r\n"


def _mc_str(s):
    e = s.encode("utf-8")
    return struct.pack("<I", len(e)) + e


def _mc_bytes(b):
    return struct.pack("<I", len(b)) + b


def _mc_record(op, content):
    return bytes([op]) + struct.pack("<Q", len(content)) + content


def build_mcap(path: str) -> str:
    """Create a deterministic uncompressed MCAP fixture with the SAME messages
    as build(), so the two containers can be cross-checked. Returns the path."""
    if os.path.exists(path):
        os.remove(path)
    parts = [MCAP_MAGIC]
    parts.append(_mc_record(0x01, _mc_str("ros2") + _mc_str("ros2bag_converter-test")))  # Header

    # Schemas. Empty data => reader falls back to built-in schema; non-empty
    # exercises the embedded-definition path (self-contained String + custom Widget).
    schemas = [
        (1, "std_msgs/msg/String", "string data\n"),
        (2, "sensor_msgs/msg/Imu", ""),
        (3, "tf2_msgs/msg/TFMessage", ""),
        (4, "my_pkg/msg/Widget", WIDGET_DEF),
    ]
    for sid, name, data in schemas:
        c = struct.pack("<H", sid) + _mc_str(name) + _mc_str("ros2msg") + _mc_bytes(data.encode("utf-8"))
        parts.append(_mc_record(0x03, c))

    channels = [(1, 1, "/chatter"), (2, 2, "/imu"), (3, 3, "/tf"), (4, 4, "/widget")]
    for cid, sid, topic in channels:
        c = struct.pack("<HH", cid, sid) + _mc_str(topic) + _mc_str("cdr") + struct.pack("<I", 0)
        parts.append(_mc_record(0x04, c))

    msgs = [
        (1, 1_000_000_000, _string_msg("hello")),
        (1, 1_500_000_000, _string_msg("world")),
        (2, 1_100_000_000, _imu_msg(1, 100_000_000)),
        (3, 1_200_000_000, _tf_msg(1, 200_000_000)),
        (4, 1_300_000_000, _widget_msg(3.14, 7, "alpha")),
        (4, 1_800_000_000, _widget_msg(-2.5, 0, "beta")),
    ]
    for seq, (cid, ts, blob) in enumerate(msgs):
        c = struct.pack("<HIQQ", cid, seq, ts, ts) + blob
        parts.append(_mc_record(0x05, c))

    parts.append(_mc_record(0x0F, struct.pack("<I", 0)))      # DataEnd
    parts.append(_mc_record(0x02, struct.pack("<QQI", 0, 0, 0)))  # Footer
    parts.append(MCAP_MAGIC)
    with open(path, "wb") as fh:
        fh.write(b"".join(parts))
    return path


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "sample.db3"
    builder = build_mcap if out.endswith(".mcap") else build
    print("wrote", builder(out))
