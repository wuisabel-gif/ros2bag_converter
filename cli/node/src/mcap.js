// SPDX-License-Identifier: Apache-2.0
'use strict';
/* ============================================================================
   MCAP (.mcap) reader — ROS 2's current default rosbag2 format. Messages are
   the same CDR payloads with schemas embedded, so only the container parser is
   new; decoding reuses ./decoder. Returns the uniform Bag interface used by
   ./bag (topics, info, eachMessage, close).

   Uncompressed chunks need nothing extra. zstd chunks use Node's built-in zstd
   (Node ≥ 22.15); lz4 is not supported here — use the .db3 export or Python CLI.
   ========================================================================== */

const fs = require('fs');
const zlib = require('zlib');
const { norm, registerEncodedDefinition, registry } = require('./decoder');

const MAGIC = Buffer.from([0x89, 0x4d, 0x43, 0x41, 0x50, 0x30, 0x0d, 0x0a]);

function decompress(comp, data) {
  if (!comp || comp.length === 0) return data;
  if (comp === 'zstd') {
    if (typeof zlib.zstdDecompressSync === 'function') return zlib.zstdDecompressSync(data);
    throw new Error('MCAP chunk uses zstd compression; needs Node ≥ 22.15 (built-in zstd), or convert the bag to .db3 / use the Python CLI.');
  }
  if (comp === 'lz4') {
    throw new Error("MCAP chunk uses lz4 compression, which this Node reader can't decompress; use the Python CLI with the 'lz4' package, or convert to .db3.");
  }
  throw new Error(`unsupported MCAP chunk compression: ${comp}`);
}

function iterRecords(buf, handle) {
  let o = 0; const end = buf.length;
  while (o + 9 <= end) {
    const op = buf.readUInt8(o);
    const ln = Number(buf.readBigUInt64LE(o + 1));
    const cstart = o + 9;
    const content = buf.subarray(cstart, cstart + ln);
    o = cstart + ln;
    handle(op, content);
    if (op === 0x02) break;   // footer — last record before trailing magic
  }
}

function openMcap(path, metadataPath) {
  const buf = fs.readFileSync(path);
  if (!buf.subarray(0, 8).equals(MAGIC)) throw new Error('Not an MCAP file — bad magic bytes.');

  const schemas = new Map();   // id -> name
  const channels = new Map();  // id -> { topic, schemaId, msgEnc }
  const msgs = new Map();      // id -> [[logTime(BigInt), data(Buffer)]]

  function handle(op, c) {
    let o = 0;
    if (op === 0x03) {                    // Schema
      const sid = c.readUInt16LE(o); o += 2;
      let n = c.readUInt32LE(o); o += 4; const name = c.toString('utf8', o, o + n); o += n;
      n = c.readUInt32LE(o); o += 4; const enc = c.toString('utf8', o, o + n); o += n;
      n = c.readUInt32LE(o); o += 4; const data = c.subarray(o, o + n); o += n;
      schemas.set(sid, name);
      if (enc === 'ros2msg' && data.length) {
        try { registerEncodedDefinition(norm(name), data.toString('utf8')); } catch (e) { /* one bad def */ }
      }
    } else if (op === 0x04) {             // Channel
      const cid = c.readUInt16LE(o); o += 2; const schemaId = c.readUInt16LE(o); o += 2;
      let n = c.readUInt32LE(o); o += 4; const topic = c.toString('utf8', o, o + n); o += n;
      n = c.readUInt32LE(o); o += 4; const msgEnc = c.toString('utf8', o, o + n); o += n;
      channels.set(cid, { topic, schemaId, msgEnc });
      if (!msgs.has(cid)) msgs.set(cid, []);
    } else if (op === 0x05) {             // Message
      const cid = c.readUInt16LE(o); o += 2; o += 4; /* seq */
      const logTime = c.readBigUInt64LE(o); o += 8; o += 8; /* publish_time */
      if (!msgs.has(cid)) msgs.set(cid, []);
      msgs.get(cid).push([logTime, c.subarray(o)]);
    } else if (op === 0x06) {             // Chunk
      o += 8; o += 8; o += 8; o += 4;     // start, end, uncompressed_size, crc
      let n = c.readUInt32LE(o); o += 4; const comp = c.toString('utf8', o, o + n); o += n;
      const recLen = Number(c.readBigUInt64LE(o)); o += 8;
      const raw = decompress(comp, c.subarray(o, o + recLen));
      iterRecords(raw, handle);
    }
  }

  iterRecords(buf.subarray(8), handle);

  const topics = [];
  let total = 0, gMin = null, gMax = null;
  const ids = [...channels.keys()].sort((a, b) => (channels.get(a).topic < channels.get(b).topic ? -1 : 1));
  for (const cid of ids) {
    const { topic, schemaId, msgEnc } = channels.get(cid);
    const type = schemas.get(schemaId) || '(unknown)';
    const list = msgs.get(cid) || [];
    let tmin = null, tmax = null;
    for (const [lt] of list) { if (tmin === null || lt < tmin) tmin = lt; if (tmax === null || lt > tmax) tmax = lt; }
    topics.push({
      id: cid, name: topic, type, fmt: msgEnc || 'cdr', cnt: list.length,
      tmin: tmin === null ? null : Number(tmin), tmax: tmax === null ? null : Number(tmax),
      decodable: registry.has(norm(type)),
    });
    total += list.length;
    if (list.length > 0) {
      const a = Number(tmin), b = Number(tmax);
      if (gMin === null || a < gMin) gMin = a;
      if (gMax === null || b > gMax) gMax = b;
    }
  }

  let distro = '';
  if (metadataPath && fs.existsSync(metadataPath)) {
    const m = fs.readFileSync(metadataPath, 'utf8'); const dm = m.match(/ros_distro:\s*(\S+)/); if (dm) distro = dm[1];
  }

  return {
    topics,
    info: { total, gMin, gMax, storage: 'mcap', distro },
    eachMessage(topicId, cb, maxRows) {
      const list = (msgs.get(topicId) || []).slice().sort((x, y) => (x[0] < y[0] ? -1 : x[0] > y[0] ? 1 : 0));
      let n = 0, truncated = false;
      for (const [lt, data] of list) {
        if (maxRows != null && n >= maxRows) { truncated = true; break; }
        cb(lt.toString(), data);   // ts as string → full-precision, like the sqlite path
        n++;
      }
      return { count: n, truncated };
    },
    close() { /* nothing to release */ },
  };
}

module.exports = { openMcap };
