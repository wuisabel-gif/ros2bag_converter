# SPDX-License-Identifier: Apache-2.0
"""rosbag2 SQLite (.db3) reader, built on the standard-library sqlite3 module.

Streams messages with a cursor rather than loading the whole DB into memory.
"""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass, field

from . import decoder


@dataclass
class Topic:
    id: int
    name: str
    type: str
    fmt: str
    cnt: int
    tmin: int | None
    tmax: int | None
    decodable: bool


@dataclass
class Bag:
    conn: sqlite3.Connection
    topics: list = field(default_factory=list)
    total: int = 0
    gmin: int | None = None
    gmax: int | None = None
    storage: str = "sqlite3"
    distro: str = ""

    def each_message(self, topic_id: int, max_rows: int | None = None):
        """Yield (timestamp_ns, data_bytes) for a topic in timestamp order."""
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


def open_bag(db3_path: str, metadata_path: str | None = None):
    """Open a rosbag2 bag, dispatching on container format (SQLite .db3 or MCAP)."""
    if not os.path.exists(db3_path):
        raise FileNotFoundError(f"file not found: {db3_path}")
    with open(db3_path, "rb") as fh:
        magic = fh.read(8)
    if magic == b"\x89MCAP0\r\n":
        from . import mcap
        return mcap.open_mcap(db3_path, metadata_path)
    try:
        conn = sqlite3.connect(f"file:{db3_path}?mode=ro", uri=True)
        # Force a read so we fail early on a non-SQLite file.
        conn.execute("SELECT name FROM sqlite_master LIMIT 1")
    except sqlite3.DatabaseError as e:
        raise ValueError(
            f'Could not open "{db3_path}" as SQLite — it may be corrupted or truncated. ({e})'
        )

    if not _table_exists(conn, "topics") or not _table_exists(conn, "messages"):
        raise ValueError('Not a rosbag2 SQLite bag — missing the "topics" / "messages" tables.')

    # Custom message definitions embedded in the bag (ROS 2 Iron and newer).
    if _table_exists(conn, "message_definitions"):
        try:
            for tt, enc, definition in conn.execute(
                "SELECT topic_type, encoding, encoded_message_definition FROM message_definitions"
            ):
                if definition and (enc == "ros2msg" or enc is None):
                    try:
                        decoder.register_encoded_definition(decoder.norm(tt), definition)
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
        bag.topics.append(Topic(tid, name, type_, fmt, cnt, tmin, tmax, decoder.is_decodable(type_)))
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
