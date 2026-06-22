#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
'use strict';
/* ============================================================================
   ros2bag-convert — inspect ROS 2 .db3 bags and export topics to CSV / JSON
   from the terminal. Same decoder as the browser app at
   https://wuisabel-gif.github.io/ros2bag_converter/
   ========================================================================== */

const fs = require('fs');
const path = require('path');
const { openBag, eachMessage } = require('../src/bag');
const { decodeMessage, flatten, csvCell } = require('../src/decoder');

const HELP = `ros2bag-convert — inspect & export ROS 2 .db3 bags (CSV / JSON)

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
`;

function parseArgs(argv) {
  const opts = { format: 'csv', output: null, topics: [], metadata: null, maxRows: 500000 };
  const positional = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const next = () => argv[++i];
    switch (a) {
      case '-h': case '--help': opts.help = true; break;
      case '-f': case '--format': opts.format = (next() || '').toLowerCase(); break;
      case '-o': case '--output': opts.output = next(); break;
      case '-t': case '--topic': opts.topics.push(next()); break;
      case '-m': case '--metadata': opts.metadata = next(); break;
      case '--max-rows': opts.maxRows = Math.max(1, parseInt(next(), 10) || 500000); break;
      default:
        if (a.startsWith('-')) throw new Error(`unknown option: ${a}`);
        positional.push(a);
    }
  }
  return { opts, positional };
}

function fmtDur(a, b) {
  if (a == null || b == null) return '—';
  const s = (Number(b) - Number(a)) / 1e9;
  if (s < 60) return s.toFixed(2) + ' s';
  return Math.floor(s / 60) + 'm ' + (s % 60).toFixed(0) + 's';
}
const fmtTime = ns => { try { return new Date(Number(ns) / 1e6).toISOString().replace('T', ' ').slice(0, 23) + ' UTC'; } catch (e) { return '—'; } };

function selectTopics(all, wanted) {
  if (!wanted.length) return all.filter(t => t.cnt > 0);
  const out = [];
  for (const name of wanted) {
    const t = all.find(x => x.name === name);
    if (!t) throw new Error(`topic not found in bag: ${name}`);
    out.push(t);
  }
  return out;
}

function cmdInfo(bag) {
  const { topics, info } = bag;
  const lines = [];
  lines.push(`Messages:   ${info.total.toLocaleString()}`);
  lines.push(`Duration:   ${fmtDur(info.gMin, info.gMax)}`);
  lines.push(`Start:      ${info.gMin == null ? '—' : fmtTime(info.gMin)}`);
  lines.push(`End:        ${info.gMax == null ? '—' : fmtTime(info.gMax)}`);
  lines.push(`Storage:    ${info.storage}${info.distro ? `  ·  distro: ${info.distro}` : ''}`);
  lines.push(`Topics:     ${topics.length}`);
  lines.push('');
  for (const t of topics) {
    lines.push(`  ${t.name}`);
    lines.push(`    type: ${t.type}   count: ${t.cnt.toLocaleString()}   ${t.decodable ? 'decodable' : 'raw bytes only'}`);
  }
  process.stdout.write(lines.join('\n') + '\n');
}

function cmdList(bag) {
  for (const t of bag.topics) {
    process.stdout.write(`${t.cnt}\t${t.type}\t${t.name}${t.decodable ? '' : '\t(raw)'}\n`);
  }
}

function cmdConvert(bag, opts) {
  const sel = selectTopics(bag.topics, opts.topics);
  if (!sel.length) throw new Error('no topics to export');
  const out = opts.output ? fs.createWriteStream(opts.output) : process.stdout;
  let truncated = false, errs = 0, done = 0;

  if (opts.format === 'json') {
    out.write('[');
    let first = true;
    for (const t of sel) {
      const res = eachMessage(bag.db, t.id, (ts, data) => {
        let decoded;
        try { decoded = t.decodable ? decodeMessage(t.type, data) : { __raw_bytes__: data.length }; }
        catch (e) { decoded = { __decode_error__: e.message, __raw_bytes__: data.length }; errs++; }
        out.write((first ? '' : ',') + '\n  ' +
          JSON.stringify({ timestamp: Number(ts) / 1e9, topic: t.name, type: t.type, data: decoded }));
        first = false; done++;
      }, opts.maxRows);
      truncated = truncated || res.truncated;
    }
    out.write('\n]\n');
  } else {
    // CSV: collect rows + union of columns in first-seen order (matches the web app).
    const multi = sel.length > 1;
    const colOrder = new Map();
    const all = [];
    for (const t of sel) {
      const res = eachMessage(bag.db, t.id, (ts, data) => {
        const f = {};
        if (t.decodable) { try { flatten(decodeMessage(t.type, data), '', f); } catch (e) { f.decode_error = e.message; errs++; } }
        else f.raw_bytes = data.length;
        for (const k in f) if (!colOrder.has(k)) colOrder.set(k, 1);
        all.push({ ts: Number(ts) / 1e9, topic: t.name, f });
        done++;
      }, opts.maxRows);
      truncated = truncated || res.truncated;
    }
    const cols = [...colOrder.keys()];
    const header = ['timestamp', ...(multi ? ['topic'] : []), ...cols];
    out.write(header.map(csvCell).join(',') + '\n');
    for (const r of all) {
      out.write([r.ts, ...(multi ? [r.topic] : []), ...cols.map(c => r.f[c] === undefined ? '' : r.f[c])].map(csvCell).join(',') + '\n');
    }
  }

  if (opts.output) out.end();
  // Diagnostics go to stderr so stdout stays a clean data stream.
  let note = `Exported ${done.toLocaleString()} messages from ${sel.length} topic(s).`;
  if (truncated) note += ` Hit the ${opts.maxRows.toLocaleString()}-row cap on some topics; raise --max-rows to include all.`;
  if (errs) note += ` ${errs} message(s) failed to decode and were flagged in the output.`;
  process.stderr.write(note + '\n');
}

async function main() {
  const { opts, positional } = parseArgs(process.argv.slice(2));
  if (opts.help || positional.length === 0) { process.stdout.write(HELP); return; }

  let command = 'convert', bagPath;
  if (['info', 'list', 'convert'].includes(positional[0])) { command = positional[0]; bagPath = positional[1]; }
  else bagPath = positional[0];

  if (!bagPath) throw new Error('no .db3 bag path given');
  if (!fs.existsSync(bagPath)) throw new Error(`file not found: ${bagPath}`);

  const bag = await openBag(bagPath, opts.metadata);
  if (command === 'info') cmdInfo(bag);
  else if (command === 'list') cmdList(bag);
  else cmdConvert(bag, opts);
  bag.db.close();
}

main().catch(e => { process.stderr.write(`ros2bag-convert: ${e.message}\n`); process.exit(1); });
