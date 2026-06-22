// SPDX-License-Identifier: Apache-2.0
'use strict';
/* ============================================================================
   ROS 2 message schema registry + .msg parser + CDR deserializer.

   This is a faithful port of the decoder that powers the browser app
   (index.html). Keep the two in sync — same wire format, same built-in
   schemas, same array-summarization caps.
   ========================================================================== */

const PRIM = new Set(['bool', 'byte', 'char', 'int8', 'uint8', 'int16', 'uint16',
  'int32', 'uint32', 'int64', 'uint64', 'float32', 'float64', 'string', 'wstring']);
const PRIM_SIZE = { bool: 1, byte: 1, char: 1, int8: 1, uint8: 1, int16: 2, uint16: 2,
  int32: 4, uint32: 4, int64: 8, uint64: 8, float32: 4, float64: 8 };

const registry = new Map();

const norm = n => n.replace('/msg/', '/').trim();

function parseMsgText(typeName, text) {
  const fields = [];
  for (const raw of text.split('\n')) {
    let line = raw.split('#')[0].trim();
    if (!line) continue;
    const parts = line.split(/\s+/);
    if (parts.length < 2) continue;
    let ftype = parts[0];
    const name = parts[1];
    if (name.includes('=')) continue;
    if (parts[1].includes('=')) continue;
    let isArray = false, arrayLen = null;
    const m = ftype.match(/^(.+?)\[(\d*)\]$/);
    if (m) { isArray = true; ftype = m[1]; arrayLen = m[2] ? parseInt(m[2], 10) : null; }
    ftype = ftype.replace(/<=\d+/, '').replace('/msg/', '/');
    fields.push({ name, type: ftype, isArray, arrayLen });
  }
  registry.set(norm(typeName), fields);
}

function registerEncodedDefinition(rootType, encoded) {
  const blocks = encoded.split(/^=+\s*$/m);
  if (blocks.length) parseMsgText(rootType, blocks[0]);
  for (let i = 1; i < blocks.length; i++) {
    const mm = blocks[i].trim().match(/^MSG:\s*(\S+)\s*\n([\s\S]*)$/);
    if (mm) parseMsgText(mm[1], mm[2]);
  }
}

function resolveType(t) {
  t = norm(t);
  if (PRIM.has(t) || registry.has(t)) return t;
  for (const k of registry.keys()) if (k.endsWith('/' + t)) return k;
  if (t === 'Header') return 'std_msgs/Header';
  return t;
}

const BUILTIN = {
  'builtin_interfaces/Time': 'int32 sec\nuint32 nanosec',
  'builtin_interfaces/Duration': 'int32 sec\nuint32 nanosec',
  'std_msgs/Header': 'builtin_interfaces/Time stamp\nstring frame_id',
  'std_msgs/String': 'string data',
  'std_msgs/Bool': 'bool data',
  'std_msgs/Empty': '',
  'std_msgs/ColorRGBA': 'float32 r\nfloat32 g\nfloat32 b\nfloat32 a',
  'geometry_msgs/Vector3': 'float64 x\nfloat64 y\nfloat64 z',
  'geometry_msgs/Point': 'float64 x\nfloat64 y\nfloat64 z',
  'geometry_msgs/Point32': 'float32 x\nfloat32 y\nfloat32 z',
  'geometry_msgs/Quaternion': 'float64 x\nfloat64 y\nfloat64 z\nfloat64 w',
  'geometry_msgs/Pose': 'geometry_msgs/Point position\ngeometry_msgs/Quaternion orientation',
  'geometry_msgs/PoseWithCovariance': 'geometry_msgs/Pose pose\nfloat64[36] covariance',
  'geometry_msgs/PoseStamped': 'std_msgs/Header header\ngeometry_msgs/Pose pose',
  'geometry_msgs/PoseWithCovarianceStamped': 'std_msgs/Header header\ngeometry_msgs/PoseWithCovariance pose',
  'geometry_msgs/Twist': 'geometry_msgs/Vector3 linear\ngeometry_msgs/Vector3 angular',
  'geometry_msgs/TwistWithCovariance': 'geometry_msgs/Twist twist\nfloat64[36] covariance',
  'geometry_msgs/TwistStamped': 'std_msgs/Header header\ngeometry_msgs/Twist twist',
  'geometry_msgs/Accel': 'geometry_msgs/Vector3 linear\ngeometry_msgs/Vector3 angular',
  'geometry_msgs/Wrench': 'geometry_msgs/Vector3 force\ngeometry_msgs/Vector3 torque',
  'geometry_msgs/Transform': 'geometry_msgs/Vector3 translation\ngeometry_msgs/Quaternion rotation',
  'geometry_msgs/TransformStamped': 'std_msgs/Header header\nstring child_frame_id\ngeometry_msgs/Transform transform',
  'tf2_msgs/TFMessage': 'geometry_msgs/TransformStamped[] transforms',
  'nav_msgs/Odometry': 'std_msgs/Header header\nstring child_frame_id\ngeometry_msgs/PoseWithCovariance pose\ngeometry_msgs/TwistWithCovariance twist',
  'nav_msgs/Path': 'std_msgs/Header header\ngeometry_msgs/PoseStamped[] poses',
  'sensor_msgs/Imu': 'std_msgs/Header header\ngeometry_msgs/Quaternion orientation\nfloat64[9] orientation_covariance\ngeometry_msgs/Vector3 angular_velocity\nfloat64[9] angular_velocity_covariance\ngeometry_msgs/Vector3 linear_acceleration\nfloat64[9] linear_acceleration_covariance',
  'sensor_msgs/Range': 'std_msgs/Header header\nuint8 radiation_type\nfloat32 field_of_view\nfloat32 min_range\nfloat32 max_range\nfloat32 range',
  'sensor_msgs/Temperature': 'std_msgs/Header header\nfloat64 temperature\nfloat64 variance',
  'sensor_msgs/FluidPressure': 'std_msgs/Header header\nfloat64 fluid_pressure\nfloat64 variance',
  'sensor_msgs/RelativeHumidity': 'std_msgs/Header header\nfloat64 relative_humidity\nfloat64 variance',
  'sensor_msgs/Illuminance': 'std_msgs/Header header\nfloat64 illuminance\nfloat64 variance',
  'sensor_msgs/MagneticField': 'std_msgs/Header header\ngeometry_msgs/Vector3 magnetic_field\nfloat64[9] magnetic_field_covariance',
  'sensor_msgs/NavSatStatus': 'int8 status\nuint16 service',
  'sensor_msgs/NavSatFix': 'std_msgs/Header header\nsensor_msgs/NavSatStatus status\nfloat64 latitude\nfloat64 longitude\nfloat64 altitude\nfloat64[9] position_covariance\nuint8 position_covariance_type',
  'sensor_msgs/PointField': 'string name\nuint32 offset\nuint8 datatype\nuint32 count',
  'sensor_msgs/PointCloud2': 'std_msgs/Header header\nuint32 height\nuint32 width\nsensor_msgs/PointField[] fields\nbool is_bigendian\nuint32 point_step\nuint32 row_step\nuint8[] data\nbool is_dense',
  'sensor_msgs/Image': 'std_msgs/Header header\nuint32 height\nuint32 width\nstring encoding\nuint8 is_bigendian\nuint32 step\nuint8[] data',
  'sensor_msgs/CompressedImage': 'std_msgs/Header header\nstring format\nuint8[] data',
  'sensor_msgs/LaserScan': 'std_msgs/Header header\nfloat32 angle_min\nfloat32 angle_max\nfloat32 angle_increment\nfloat32 time_increment\nfloat32 scan_time\nfloat32 range_min\nfloat32 range_max\nfloat32[] ranges\nfloat32[] intensities',
  'sensor_msgs/JointState': 'std_msgs/Header header\nstring[] name\nfloat64[] position\nfloat64[] velocity\nfloat64[] effort',
  'sensor_msgs/Joy': 'std_msgs/Header header\nfloat32[] axes\nint32[] buttons',
  'sensor_msgs/BatteryState': 'std_msgs/Header header\nfloat32 voltage\nfloat32 temperature\nfloat32 current\nfloat32 charge\nfloat32 capacity\nfloat32 design_capacity\nfloat32 percentage\nuint8 power_supply_status\nuint8 power_supply_health\nuint8 power_supply_technology\nbool present\nfloat32[] cell_voltage\nfloat32[] cell_temperature\nstring location\nstring serial_number',
};
for (const [k, v] of Object.entries(BUILTIN)) parseMsgText(k, v);
for (const [k, p] of Object.entries({ Float32: 'float32', Float64: 'float64', Int8: 'int8',
  Int16: 'int16', Int32: 'int32', Int64: 'int64', UInt8: 'uint8', UInt16: 'uint16',
  UInt32: 'uint32', UInt64: 'uint64', Byte: 'byte', Char: 'char' })) {
  parseMsgText('std_msgs/' + k, p + ' data');
}

/* ----------------------------------------------------------------------------
   CDR reader — ROS 2 wire format
   -------------------------------------------------------------------------- */
const TXT = new TextDecoder('utf-8', { fatal: false });
const numv = b => { const n = Number(b); return Number.isSafeInteger(n) ? n : b.toString(); };
const BYTE_ARR_CAP = 1024, PRIM_ARR_CAP = 8192;

class CDR {
  constructor(u8) {
    this.u8 = u8;
    this.dv = new DataView(u8.buffer, u8.byteOffset, u8.byteLength);
    this.le = u8.length > 1 ? (u8[1] & 1) === 1 : true;
    this.origin = 4; this.off = 4;
  }
  align(n) { const rel = (this.off - this.origin) % n; if (rel) this.off += n - rel; }
  rByte() { return this.dv.getUint8(this.off++); }
  rI8() { return this.dv.getInt8(this.off++); }
  rU16() { this.align(2); const v = this.dv.getUint16(this.off, this.le); this.off += 2; return v; }
  rI16() { this.align(2); const v = this.dv.getInt16(this.off, this.le); this.off += 2; return v; }
  rU32() { this.align(4); const v = this.dv.getUint32(this.off, this.le); this.off += 4; return v; }
  rI32() { this.align(4); const v = this.dv.getInt32(this.off, this.le); this.off += 4; return v; }
  rF32() { this.align(4); const v = this.dv.getFloat32(this.off, this.le); this.off += 4; return v; }
  rF64() { this.align(8); const v = this.dv.getFloat64(this.off, this.le); this.off += 8; return v; }
  rI64() { this.align(8); const v = this.dv.getBigInt64(this.off, this.le); this.off += 8; return numv(v); }
  rU64() { this.align(8); const v = this.dv.getBigUint64(this.off, this.le); this.off += 8; return numv(v); }
  rStr() {
    this.align(4);
    const n = this.dv.getUint32(this.off, this.le); this.off += 4;
    if (n === 0) return '';
    const bytes = this.u8.subarray(this.off, this.off + n); this.off += n;
    let len = n; if (len > 0 && bytes[len - 1] === 0) len--;
    return TXT.decode(bytes.subarray(0, len));
  }
}

function readScalar(cdr, type) {
  switch (type) {
    case 'bool': return cdr.rByte() !== 0;
    case 'byte': case 'uint8': case 'char': return cdr.rByte();
    case 'int8': return cdr.rI8();
    case 'int16': return cdr.rI16();
    case 'uint16': return cdr.rU16();
    case 'int32': return cdr.rI32();
    case 'uint32': return cdr.rU32();
    case 'int64': return cdr.rI64();
    case 'uint64': return cdr.rU64();
    case 'float32': return cdr.rF32();
    case 'float64': return cdr.rF64();
    case 'string': case 'wstring': return cdr.rStr();
    default: return readType(cdr, resolveType(type));
  }
}
function readField(cdr, f) {
  if (!f.isArray) return readScalar(cdr, f.type);
  let len = f.arrayLen;
  if (len === null) { cdr.align(4); len = cdr.rU32(); }
  const t = norm(f.type);
  if (PRIM.has(t) && t !== 'string' && t !== 'wstring') {
    const sz = PRIM_SIZE[t];
    const isByte = (t === 'uint8' || t === 'byte' || t === 'char' || t === 'int8');
    const summarize = isByte ? len > BYTE_ARR_CAP : len > PRIM_ARR_CAP;
    if (summarize) { if (sz > 1) cdr.align(sz); cdr.off += len * sz; return { __array__: t, length: len }; }
    const out = new Array(len);
    for (let i = 0; i < len; i++) out[i] = readScalar(cdr, t);
    return out;
  }
  const out = new Array(len);
  for (let i = 0; i < len; i++) out[i] = readScalar(cdr, t);
  return out;
}
function readType(cdr, typeName) {
  const fields = registry.get(typeName);
  if (!fields) throw new Error('no schema for ' + typeName);
  const obj = {};
  for (const f of fields) obj[f.name] = readField(cdr, f);
  return obj;
}
function decodeMessage(typeName, bytes) { return readType(new CDR(bytes), norm(typeName)); }

/* ----------------------------------------------------------------------------
   CSV flattening — mirrors the browser export exactly
   -------------------------------------------------------------------------- */
function flatten(obj, prefix, out) {
  for (const k in obj) {
    const v = obj[k], key = prefix ? prefix + '.' + k : k;
    if (v === null || v === undefined) out[key] = '';
    else if (typeof v !== 'object') out[key] = v;
    else if (Array.isArray(v)) {
      if (v.length && typeof v[0] === 'object') out[key] = JSON.stringify(v);
      else if (v.length > 64) out[key] = `[${v.length} values]`;
      else v.forEach((el, i) => { if (el && typeof el === 'object') flatten(el, `${key}.${i}`, out); else out[`${key}.${i}`] = el; });
    }
    else if (v.__array__) out[key] = `[${v.length} × ${v.__array__}]`;
    else flatten(v, key, out);
  }
}
function csvCell(v) { if (v == null) return ''; let s = String(v); if (/[",\n\r]/.test(s)) s = '"' + s.replace(/"/g, '""') + '"'; return s; }

module.exports = {
  PRIM, registry, norm, parseMsgText, registerEncodedDefinition, resolveType,
  decodeMessage, flatten, csvCell, isDecodable: t => registry.has(norm(t || '')),
};
