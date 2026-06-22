# SPDX-License-Identifier: Apache-2.0
"""MCAP (.mcap) reader for ROS 2 bags.

MCAP is ROS 2's current default rosbag2 storage format. Messages are the same
CDR payloads as the SQLite format, and schemas (ros2msg) are embedded — so this
module only parses the MCAP container and reuses the shared CDR decoder.

Uncompressed chunks (and chunk-less files) need only the standard library.
zstd / lz4 chunk compression needs the optional `zstandard` / `lz4` packages;
a clear error is raised if such a chunk is encountered without the library.
"""

from __future__ import annotations

import io
import struct

from . import decoder
from .bag import Topic

MAGIC = b"\x89MCAP0\r\n"

# record opcodes
_HEADER, _FOOTER, _SCHEMA, _CHANNEL, _MESSAGE, _CHUNK, _DATA_END = (
    0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x0F,
)


class _Reader:
    __slots__ = ("b", "o")

    def __init__(self, buf, off=0):
        self.b = buf
        self.o = off

    def u8(self):
        v = self.b[self.o]; self.o += 1; return v

    def u16(self):
        v = struct.unpack_from("<H", self.b, self.o)[0]; self.o += 2; return v

    def u32(self):
        v = struct.unpack_from("<I", self.b, self.o)[0]; self.o += 4; return v

    def u64(self):
        v = struct.unpack_from("<Q", self.b, self.o)[0]; self.o += 8; return v

    def s(self):
        n = self.u32(); v = self.b[self.o:self.o + n].decode("utf-8", "replace"); self.o += n; return v

    def bytes_u32(self):
        n = self.u32(); v = self.b[self.o:self.o + n]; self.o += n; return v


def _iter_records(buf, start, end):
    o = start
    while o + 9 <= end:
        op = buf[o]
        ln = struct.unpack_from("<Q", buf, o + 1)[0]
        cstart = o + 9
        content = buf[cstart:cstart + ln]
        o = cstart + ln
        yield op, content
        if op == _FOOTER:
            break


def _decompress(comp, data, uncompressed_size):
    if not comp:
        return data
    if comp == "zstd":
        try:
            import zstandard
        except ImportError:
            raise RuntimeError(
                "MCAP chunk uses zstd compression; install 'zstandard' (pip install zstandard) to read it."
            )
        return zstandard.ZstdDecompressor().stream_reader(io.BytesIO(data)).read()
    if comp == "lz4":
        try:
            import lz4.frame as lz4frame
        except ImportError:
            raise RuntimeError(
                "MCAP chunk uses lz4 compression; install 'lz4' (pip install lz4) to read it."
            )
        return lz4frame.decompress(data)
    raise RuntimeError(f"unsupported MCAP chunk compression: {comp!r}")


class McapBag:
    """Duck-typed like bag.Bag: .topics, .total, .gmin/.gmax/.storage/.distro,
    .each_message(topic_id, max_rows), .close()."""

    def __init__(self):
        self.topics = []
        self.total = 0
        self.gmin = None
        self.gmax = None
        self.storage = "mcap"
        self.distro = ""
        self._msgs = {}  # channel_id -> list[(log_time, data)]
        self._truncated = False

    def each_message(self, topic_id, max_rows=None):
        data = sorted(self._msgs.get(topic_id, []), key=lambda x: x[0])
        self._truncated = False
        for i, (log_time, blob) in enumerate(data):
            if max_rows is not None and i >= max_rows:
                self._truncated = True
                break
            yield log_time, blob

    def close(self):
        pass


def open_mcap(path: str, metadata_path: "str | None" = None) -> McapBag:
    with open(path, "rb") as fh:
        buf = fh.read()
    if buf[:8] != MAGIC:
        raise ValueError("Not an MCAP file — bad magic bytes.")

    schemas = {}   # id -> name
    channels = {}  # id -> (topic, schema_id, msg_encoding)
    bag = McapBag()

    def handle(op, content):
        r = _Reader(content)
        if op == _SCHEMA:
            sid = r.u16(); name = r.s(); enc = r.s(); data = r.bytes_u32()
            schemas[sid] = name
            if enc == "ros2msg" and data:
                try:
                    decoder.register_encoded_definition(decoder.norm(name), data.decode("utf-8", "replace"))
                except Exception:
                    pass
        elif op == _CHANNEL:
            cid = r.u16(); schema_id = r.u16(); topic = r.s(); msg_enc = r.s()
            channels[cid] = (topic, schema_id, msg_enc)
            bag._msgs.setdefault(cid, [])
        elif op == _MESSAGE:
            cid = r.u16(); r.u32(); log_time = r.u64(); r.u64()
            bag._msgs.setdefault(cid, []).append((log_time, content[r.o:]))
        elif op == _CHUNK:
            r.u64(); r.u64(); usize = r.u64(); r.u32(); comp = r.s()
            n = r.u64()                      # records byte-length (uint64)
            records = r.b[r.o:r.o + n]
            raw = _decompress(comp, records, usize)
            for iop, icontent in _iter_records(raw, 0, len(raw)):
                handle(iop, icontent)

    for op, content in _iter_records(buf, 8, len(buf)):
        handle(op, content)

    for cid in sorted(channels, key=lambda c: channels[c][0]):
        topic, schema_id, msg_enc = channels[cid]
        type_ = schemas.get(schema_id) or "(unknown)"
        mlist = bag._msgs.get(cid, [])
        cnt = len(mlist)
        tmin = min((t for t, _ in mlist), default=None)
        tmax = max((t for t, _ in mlist), default=None)
        bag.topics.append(Topic(cid, topic, type_, msg_enc or "cdr", cnt, tmin, tmax,
                                decoder.is_decodable(type_)))
        bag.total += cnt
        if cnt > 0:
            bag.gmin = tmin if bag.gmin is None else min(bag.gmin, tmin)
            bag.gmax = tmax if bag.gmax is None else max(bag.gmax, tmax)

    if metadata_path:
        import os
        import re
        if os.path.exists(metadata_path):
            with open(metadata_path, "r", encoding="utf-8", errors="replace") as fh:
                meta = fh.read()
            dm = re.search(r"ros_distro:\s*(\S+)", meta)
            if dm:
                bag.distro = dm.group(1)
    return bag
