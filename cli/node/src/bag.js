// SPDX-License-Identifier: Apache-2.0
'use strict';
/* ============================================================================
   rosbag2 reader — dispatches on container format:
     • SQLite .db3  (via sql.js, pure WASM)
     • MCAP  .mcap  (via ./mcap)
   Both openers return a uniform Bag object:
     { topics, info, eachMessage(topicId, cb, maxRows) -> {count,truncated}, close() }
   ========================================================================== */

const fs = require('fs');
const initSqlJs = require('sql.js');
const { norm, registerEncodedDefinition, registry } = require('./decoder');

const MCAP_MAGIC = Buffer.from([0x89, 0x4d, 0x43, 0x41, 0x50, 0x30, 0x0d, 0x0a]);

let SQL = null;
async function ensureSQL() {
  if (!SQL) SQL = await initSqlJs();
  return SQL;
}

function tableExists(db, name) {
  const r = db.exec(`SELECT name FROM sqlite_master WHERE type='table' AND name='${name}'`);
  return r.length > 0 && r[0].values.length > 0;
}

/** Open a rosbag2 bag, dispatching on the file's magic bytes. */
async function openBag(path, metadataPath) {
  if (!fs.existsSync(path)) throw new Error(`file not found: ${path}`);
  const head = Buffer.alloc(8);
  const fd = fs.openSync(path, 'r');
  try { fs.readSync(fd, head, 0, 8, 0); } finally { fs.closeSync(fd); }
  if (head.equals(MCAP_MAGIC)) {
    return require('./mcap').openMcap(path, metadataPath);
  }
  return openSqliteBag(path, metadataPath);
}

async function openSqliteBag(db3Path, metadataPath) {
  await ensureSQL();
  const bytes = new Uint8Array(fs.readFileSync(db3Path));
  let db;
  try {
    db = new SQL.Database(bytes);
  } catch (e) {
    throw new Error(`Could not open "${db3Path}" as SQLite — it may be corrupted or truncated. (${e.message})`);
  }
  if (!tableExists(db, 'topics') || !tableExists(db, 'messages')) {
    throw new Error('Not a rosbag2 SQLite bag — missing the "topics" / "messages" tables.');
  }

  if (tableExists(db, 'message_definitions')) {
    try {
      const r = db.exec('SELECT topic_type, encoding, encoded_message_definition FROM message_definitions');
      if (r.length) for (const [tt, enc, def] of r[0].values) {
        if (def && (enc === 'ros2msg' || enc == null)) {
          try { registerEncodedDefinition(norm(tt), def); } catch (e) { /* one bad def */ }
        }
      }
    } catch (e) { /* unreadable — fall back to built-ins */ }
  }

  const rows = db.exec(`SELECT t.id, t.name, t.type, COALESCE(t.serialization_format,'cdr') fmt,
      COUNT(m.id) cnt, MIN(m.timestamp) tmin, MAX(m.timestamp) tmax
    FROM topics t LEFT JOIN messages m ON m.topic_id=t.id GROUP BY t.id ORDER BY t.name`);

  const topics = [];
  let gMin = null, gMax = null, total = 0;
  if (rows.length) for (const [id, name, type, fmt, cnt, tmin, tmax] of rows[0].values) {
    topics.push({ id, name, type: type || '(unknown)', fmt, cnt, tmin, tmax,
      decodable: registry.has(norm(type || '')) });
    total += cnt;
    if (cnt > 0) { if (gMin === null || tmin < gMin) gMin = tmin; if (gMax === null || tmax > gMax) gMax = tmax; }
  }

  let storage = 'sqlite3', distro = '';
  if (metadataPath && fs.existsSync(metadataPath)) {
    const metaText = fs.readFileSync(metadataPath, 'utf8');
    const sm = metaText.match(/storage_identifier:\s*(\S+)/); if (sm) storage = sm[1];
    const dm = metaText.match(/ros_distro:\s*(\S+)/); if (dm) distro = dm[1];
  }

  return {
    topics,
    info: { total, gMin, gMax, storage, distro },
    eachMessage(topicId, cb, maxRows) {
      const stmt = db.prepare('SELECT CAST(timestamp AS TEXT) ts, data FROM messages WHERE topic_id=$id ORDER BY timestamp');
      stmt.bind({ $id: topicId });
      let n = 0, truncated = false;
      while (stmt.step()) {
        if (maxRows != null && n >= maxRows) { truncated = true; break; }
        const r = stmt.getAsObject();
        cb(r.ts, r.data);
        n++;
      }
      stmt.free();
      return { count: n, truncated };
    },
    close() { try { db.close(); } catch (e) { /* ignore */ } },
  };
}

module.exports = { openBag };
