// SPDX-License-Identifier: Apache-2.0
'use strict';
/* Minimal smoke test: encode known CDR blobs, build a synthetic rosbag2 .db3,
   and exercise decode + bag reading end to end. Run: `node test/smoke.test.js`. */

const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const initSqlJs = require('sql.js');
const { decodeMessage, flatten } = require('../src/decoder');
const { openBag } = require('../src/bag');

/* A tiny little-endian CDR encoder that mirrors the reader's origin-relative
   alignment (origin = 4, after the encapsulation header). */
class Enc {
  constructor() { this.buf = [0, 1, 0, 0]; this.origin = 4; } // LE encapsulation
  align(n) { const rel = (this.buf.length - this.origin) % n; if (rel) for (let i = 0; i < n - rel; i++) this.buf.push(0); }
  u8(v) { this.buf.push(v & 0xff); }
  u32(v) { this.align(4); const b = Buffer.alloc(4); b.writeUInt32LE(v >>> 0); for (const x of b) this.buf.push(x); }
  f64(v) { this.align(8); const b = Buffer.alloc(8); b.writeDoubleLE(v); for (const x of b) this.buf.push(x); }
  str(s) { const sb = Buffer.from(s, 'utf8'); this.u32(sb.length + 1); for (const x of sb) this.buf.push(x); this.buf.push(0); }
  bytes() { return new Uint8Array(this.buf); }
}

let passed = 0;
const ok = (name) => { passed++; console.log(`  ✓ ${name}`); };

// 1) std_msgs/String round-trips.
{
  const e = new Enc(); e.str('hello world');
  const m = decodeMessage('std_msgs/String', e.bytes());
  assert.strictEqual(m.data, 'hello world');
  ok('decode std_msgs/String');
}

// 2) geometry_msgs/Vector3 (3 × float64) round-trips with correct alignment.
{
  const e = new Enc(); e.f64(1.5); e.f64(-2.5); e.f64(3.0);
  const m = decodeMessage('geometry_msgs/Vector3', e.bytes());
  assert.strictEqual(m.x, 1.5); assert.strictEqual(m.y, -2.5); assert.strictEqual(m.z, 3.0);
  ok('decode geometry_msgs/Vector3 (alignment)');
}

// 3) Nested + flatten: geometry_msgs/PoseStamped header has padding before float64s.
{
  const e = new Enc();
  // std_msgs/Header: builtin_interfaces/Time (int32 sec, uint32 nanosec) + string frame_id
  e.u32(7); e.u32(250000000); e.str('map');
  // geometry_msgs/Pose: Point(3×f64) + Quaternion(4×f64)
  e.f64(10); e.f64(20); e.f64(0); e.f64(0); e.f64(0); e.f64(0); e.f64(1);
  const m = decodeMessage('geometry_msgs/PoseStamped', e.bytes());
  assert.strictEqual(m.header.frame_id, 'map');
  assert.strictEqual(m.pose.position.x, 10);
  assert.strictEqual(m.pose.orientation.w, 1);
  const flat = {}; flatten(m, '', flat);
  assert.strictEqual(flat['pose.position.x'], 10);
  assert.strictEqual(flat['header.frame_id'], 'map');
  ok('decode + flatten geometry_msgs/PoseStamped');
}

// 4) Full pipeline: build a synthetic .db3 and read it back.
(async () => {
  const SQL = await initSqlJs();
  const db = new SQL.Database();
  db.run(`CREATE TABLE topics(id INTEGER PRIMARY KEY, name TEXT, type TEXT, serialization_format TEXT);
          CREATE TABLE messages(id INTEGER PRIMARY KEY, topic_id INTEGER, timestamp INTEGER, data BLOB);`);
  db.run(`INSERT INTO topics VALUES (1,'/chatter','std_msgs/msg/String','cdr');`);
  const blob = (new Enc(), (() => { const e = new Enc(); e.str('from a bag'); return e.bytes(); })());
  const stmt = db.prepare('INSERT INTO messages VALUES (?,?,?,?)');
  stmt.run([1, 1, 1000000000, blob]); stmt.free();

  const tmp = path.join(os.tmpdir(), `ros2bag_smoke_${process.pid}.db3`);
  fs.writeFileSync(tmp, Buffer.from(db.export()));
  db.close();

  const bag = await openBag(tmp);
  assert.strictEqual(bag.topics.length, 1);
  assert.strictEqual(bag.topics[0].name, '/chatter');
  assert.strictEqual(bag.topics[0].cnt, 1);
  assert.strictEqual(bag.topics[0].decodable, true);

  let got = null;
  bag.eachMessage(1, (ts, data) => { got = decodeMessage(bag.topics[0].type, data).data; });
  assert.strictEqual(got, 'from a bag');
  bag.close();
  fs.unlinkSync(tmp);
  ok('full pipeline: synthetic .db3 → openBag → decode');

  // 5) MCAP: build a minimal uncompressed .mcap and read it back.
  const mc = path.join(os.tmpdir(), `ros2bag_smoke_${process.pid}.mcap`);
  fs.writeFileSync(mc, buildMcap());
  const mbag = await openBag(mc);
  assert.strictEqual(mbag.info.storage, 'mcap');
  assert.strictEqual(mbag.topics.length, 1);
  assert.strictEqual(mbag.topics[0].name, '/chatter');
  let mgot = null;
  mbag.eachMessage(1, (ts, data) => { mgot = decodeMessage(mbag.topics[0].type, data).data; });
  assert.strictEqual(mgot, 'from an mcap');
  mbag.close();
  fs.unlinkSync(mc);
  ok('full pipeline: synthetic .mcap → openBag → decode');

  console.log(`\n${passed} checks passed.`);
})().catch(e => { console.error('FAILED:', e); process.exit(1); });

// Build a minimal valid uncompressed MCAP with one String message.
function buildMcap() {
  const MAGIC = Buffer.from([0x89, 0x4d, 0x43, 0x41, 0x50, 0x30, 0x0d, 0x0a]);
  const str = s => { const b = Buffer.from(s, 'utf8'); const len = Buffer.alloc(4); len.writeUInt32LE(b.length); return Buffer.concat([len, b]); };
  const bytesU32 = b => { const len = Buffer.alloc(4); len.writeUInt32LE(b.length); return Buffer.concat([len, b]); };
  const u16 = v => { const b = Buffer.alloc(2); b.writeUInt16LE(v); return b; };
  const rec = (op, content) => { const h = Buffer.alloc(9); h.writeUInt8(op, 0); h.writeBigUInt64LE(BigInt(content.length), 1); return Buffer.concat([h, content]); };
  const parts = [MAGIC];
  parts.push(rec(0x01, Buffer.concat([str('ros2'), str('smoke')])));                                  // Header
  parts.push(rec(0x03, Buffer.concat([u16(1), str('std_msgs/msg/String'), str('ros2msg'), bytesU32(Buffer.from('string data\n'))]))); // Schema
  parts.push(rec(0x04, Buffer.concat([u16(1), u16(1), str('/chatter'), str('cdr'), Buffer.alloc(4)]))); // Channel (empty metadata map)
  const payload = (() => { const e = new Enc(); e.str('from an mcap'); return Buffer.from(e.bytes()); })();
  const msg = Buffer.concat([u16(1), Buffer.alloc(4), (() => { const b = Buffer.alloc(8); b.writeBigUInt64LE(1000000000n); return b; })(), Buffer.alloc(8), payload]);
  parts.push(rec(0x05, msg));                                                                          // Message
  parts.push(rec(0x0f, Buffer.alloc(4)));                                                              // DataEnd
  parts.push(rec(0x02, Buffer.alloc(20)));                                                             // Footer
  parts.push(MAGIC);
  return Buffer.concat(parts);
}
