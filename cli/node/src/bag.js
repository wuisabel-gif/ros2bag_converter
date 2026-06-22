// SPDX-License-Identifier: Apache-2.0
'use strict';
/* ============================================================================
   rosbag2 SQLite (.db3) reader — built on sql.js (pure-WASM SQLite, no native
   build step). Mirrors how index.html reads the bag in the browser.
   ========================================================================== */

const fs = require('fs');
const initSqlJs = require('sql.js');
const { norm, registerEncodedDefinition, registry } = require('./decoder');

let SQL = null;
async function ensureSQL() {
  if (!SQL) SQL = await initSqlJs();
  return SQL;
}

function tableExists(db, name) {
  const r = db.exec(`SELECT name FROM sqlite_master WHERE type='table' AND name='${name}'`);
  return r.length > 0 && r[0].values.length > 0;
}

/**
 * Open a .db3 bag. Returns { db, topics, info }.
 * `topics` is [{ id, name, type, fmt, cnt, tmin, tmax, decodable }].
 * Registers any custom message_definitions found in the bag (Iron+).
 */
async function openBag(db3Path, metadataPath) {
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

  // Custom message definitions embedded in the bag (ROS 2 Iron and newer).
  if (tableExists(db, 'message_definitions')) {
    try {
      const r = db.exec('SELECT topic_type, encoding, encoded_message_definition FROM message_definitions');
      if (r.length) for (const [tt, enc, def] of r[0].values) {
        if (def && (enc === 'ros2msg' || enc == null)) {
          try { registerEncodedDefinition(norm(tt), def); } catch (e) { /* ignore one bad def */ }
        }
      }
    } catch (e) { /* table present but unreadable — fall back to built-ins */ }
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

  return { db, topics, info: { total, gMin, gMax, storage, distro } };
}

/** Iterate messages of a topic in timestamp order: yields { ts (BigInt-safe string), data (Uint8Array) }. */
function eachMessage(db, topicId, cb, maxRows) {
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
}

module.exports = { openBag, eachMessage };
