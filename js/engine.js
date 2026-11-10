/* Generator and validator. No UI and no storage here, so it can move to the server later.
   Messages returned by check* functions are already HTML-escaped. */

// IPs that must never repeat across records (active or in the trash)
var UNIQ = ['RTU IP-1', 'RTU IP-2', 'PLC IP-1', 'PLC IP-2', 'RTU Internal IP-1', 'RTU Internal IP-2', 'RTU-HMI IP', 'IES Moxa IP'];
// infrastructure addresses: shared by design (same for every record of a range), never given to a device
var INFRA = ['Engg. Laptop IP', 'Gateway-1', 'Gateway-2'];
var IPF = UNIQ.concat(INFRA);
var ALLF = ['RTU IP-1', 'RTU IP-2', 'PLC IP-1', 'PLC IP-2', 'RTU Internal IP-1', 'RTU Internal IP-2', 'RTU-HMI IP', 'Engg. Laptop IP', 'IES Moxa IP', 'Gateway-1', 'Gateway-2', 'Subnet Mask', 'RTU VLAN', 'PLC VLAN'];
var COLS = ['Facility Name', 'GCP & Ring', 'Vendor', 'Date', 'TSU PAN Engineer'].concat(ALLF);
var PLACEHOLDER = /^(USED|UNKNOWN|-|)$/;

function h(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

/* ---------- address rules (section 4.3) ---------- */
function build(gcp, vendor, n) {
  var g = CFG.gcps[gcp], p = g[0] + '.' + g[1] + '.', v = CFG.vlan[gcp], r, A, B;
  if (vendor === 'Yokogawa') {
    A = p + '20.'; B = p + '21.';
    r = {
      'RTU IP-1': A + (n + 168), 'RTU IP-2': B + (n + 168), 'PLC IP-1': A + (n + 84), 'PLC IP-2': B + (n + 84),
      'RTU Internal IP-1': A + n, 'RTU Internal IP-2': B + n, 'RTU-HMI IP': A + (n + 210), 'IES Moxa IP': p + '10.' + n,
      'Engg. Laptop IP': A + 250, 'Gateway-1': A + 253, 'Gateway-2': B + 253
    };
  } else {
    var s = 4 * (n - 1) + 1;
    A = p + '100.'; B = p + '101.';
    r = {
      'RTU IP-1': A + s, 'RTU IP-2': A + (s + 1), 'PLC IP-1': A + (s + 2), 'PLC IP-2': A + (s + 3),
      'RTU-HMI IP': B + n, 'IES Moxa IP': p + '11.' + n, 'Engg. Laptop IP': A + 250, 'Gateway-1': A + 253, 'Gateway-2': B + 253
    };
  }
  r['Subnet Mask'] = CFG.mask; r['RTU VLAN'] = v[0]; r['PLC VLAN'] = v[1];
  return r;
}
function configured(gcp, vendor) { return !!CFG.gcps[gcp] && CFG.vendors.indexOf(vendor) >= 0; }

/* ---------- IPv4 helpers ---------- */
// "018.1.20.07" -> "18.1.20.7"; anything that is not a valid dotted IPv4 -> null
function canonIp(s) {
  var m = /^\s*(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\s*$/.exec(String(s == null ? '' : s));
  if (!m) return null;
  var o = m.slice(1).map(Number);
  return o.every(function (x) { return x <= 255; }) ? o.join('.') : null;
}
function ipInt(ip) { return ip.split('.').reduce(function (a, o) { return a * 256 + Number(o); }, 0); }
// prefix length of a subnet mask, or -1 when the mask is not valid (ones must be contiguous)
function maskBits(mask) {
  var c = canonIp(mask); if (!c) return -1;
  var bits = ipInt(c).toString(2).padStart(32, '0');
  return /^1+0*$/.test(bits) ? bits.indexOf('0') < 0 ? 32 : bits.indexOf('0') : -1;
}
// 'network' / 'broadcast' when the IP is the first or last address of its subnet, else ''
function edgeAddress(ip, mask) {
  var b = maskBits(mask); if (b < 1 || b > 30) return '';
  var host = ipInt(ip) % Math.pow(2, 32 - b);
  return host === 0 ? 'network' : host === Math.pow(2, 32 - b) - 1 ? 'broadcast' : '';
}
function sameSubnet(a, b, mask) {
  var bits = maskBits(mask); if (bits < 1) return true;
  var d = Math.pow(2, 32 - bits);
  return Math.floor(ipInt(a) / d) === Math.floor(ipInt(b) / d);
}

/* ---------- what is already used ---------- */
function key(ip) { return canonIp(ip) || String(ip); }
// every unique IP in use -> record name (records in the trash still count: they stay reserved)
function taken(recs, skipId) {
  var m = {};
  recs.forEach(function (r) { if (r.id !== skipId) UNIQ.forEach(function (f) { if (r.ips[f]) m[key(r.ips[f])] = r.name; }); });
  return m;
}
// gateway and laptop addresses in use -> record name (a device may never get one of these)
function infraUsed(recs, skipId) {
  var m = {};
  recs.forEach(function (r) { if (r.id !== skipId) INFRA.forEach(function (f) { if (r.ips[f]) m[key(r.ips[f])] = r.name; }); });
  return m;
}
function busyHost(ips, t, inf) {
  return UNIQ.some(function (f) { return ips[f] && (t[key(ips[f])] || inf[key(ips[f])]); });
}

/* ---------- allocation (section 4.4): first free host number ---------- */
function allocate(gcp, vendor, recs, skipId) {
  var t = taken(recs, skipId), inf = infraUsed(recs, skipId), skipped = [];
  for (var n = 1; n <= CFG.max[vendor]; n++) {
    var ips = build(gcp, vendor, n);
    if (!busyHost(ips, t, inf)) return { n: n, ips: ips, skipped: skipped };
    skipped.push(n);
  }
  return { full: true, skipped: skipped };
}
function usage(gcp, vendor, recs) {
  var t = taken(recs), inf = infraUsed(recs), free = 0, m = CFG.max[vendor], next = 0;
  for (var n = 1; n <= m; n++) {
    if (!busyHost(build(gcp, vendor, n), t, inf)) { free++; if (!next) next = n; }
  }
  return { used: m - free, max: m, next: next };
}
// host number n when the IPs follow the rule of this range exactly, else 0
function ruleHost(gcp, vendor, ips) {
  if (!configured(gcp, vendor)) return 0;
  for (var n = 1; n <= CFG.max[vendor]; n++) {
    var b = build(gcp, vendor, n);
    if (UNIQ.every(function (f) { return (b[f] || '') === (ips[f] ? key(ips[f]) : ''); })) return n;
  }
  return 0;
}

/* ---------- names ---------- */
function checkName(name, recs, skipId) {
  name = String(name).trim().toUpperCase();
  if (!/^[A-Z]{4}-\d{1,5}$/.test(name) || CFG.facilities.indexOf(name.split('-')[0]) < 0)
    return 'Name must look like UTMN-1000: a facility from the list, a dash, then the well number (1 to 5 digits).';
  return recs.some(function (r) { return r.id !== skipId && String(r.name).toUpperCase() === name; })
    ? 'The name ' + h(name) + ' already exists' + (recs.some(function (r) { return r.id !== skipId && r.del && String(r.name).toUpperCase() === name; }) ? ' (in the trash)' : '') + '.'
    : '';
}
function isStdName(name) { return /^[A-Z]{4}-\d{1,5}$/i.test(String(name)); }
// person names typed by the engineer: trimmed, inner spaces collapsed
function cleanPerson(s) { return String(s == null ? '' : s).trim().replace(/\s+/g, ' '); }
function checkPerson(s) {
  s = cleanPerson(s);
  if (s.length < 2 || s.length > 40) return 'Type your name (2 to 40 characters).';
  if (!/^[\p{L}][\p{L}\p{M} .'-]*$/u.test(s)) return 'A name may only contain letters, spaces, dots, dashes and apostrophes.';
  return '';
}

/* ---------- IP conflict check for a full record ---------- */
function checkIps(ips, recs, skipId) {
  var t = taken(recs, skipId), inf = infraUsed(recs, skipId), e = [], seen = {};
  UNIQ.forEach(function (f) {
    if (!ips[f]) return;
    var k = key(ips[f]);
    if (seen[k]) e.push(h(f + ' ' + ips[f]) + ' repeats ' + h(seen[k]) + ' of the same record');
    else if (t[k]) e.push(h(f + ' ' + ips[f]) + ' is already used by ' + h(t[k]));
    else if (inf[k]) e.push(h(f + ' ' + ips[f]) + ' is a gateway or laptop address of ' + h(inf[k]));
    seen[k] = f;
  });
  return e;
}

/* ---------- one imported row ----------
   x: object keyed by COLS. idx: makeIndex(records); rows accepted earlier in the same file are added
   to it with indexAdd(), so later rows are checked against them too.
   Returns { rec, errors[], warnings[] }; rec is null when there are errors. */
function makeIndex(recs) {
  var idx = { names: {}, t: taken(recs), inf: infraUsed(recs) };
  recs.forEach(function (r) { idx.names[String(r.name).toUpperCase()] = r.del ? 'trash' : 'active'; });
  return idx;
}
function indexAdd(idx, r) {
  idx.names[String(r.name).toUpperCase()] = 'file';
  UNIQ.forEach(function (f) { if (r.ips[f]) idx.t[key(r.ips[f])] = r.name; });
  INFRA.forEach(function (f) { if (r.ips[f]) idx.inf[key(r.ips[f])] = r.name; });
}
function checkImportRow(x, idx) {
  var errors = [], warnings = [], val = function (k) { return String(x[k] == null ? '' : x[k]).trim(); };
  var name = val('Facility Name').toUpperCase(), ph = PLACEHOLDER.test(name);
  if (name.length > 40) errors.push('Facility Name is longer than 40 characters');
  else if (!ph) {
    if (!/^[A-Z]{4}-\d{1,5}$/.test(name) || CFG.facilities.indexOf(name.split('-')[0]) < 0) errors.push('Facility Name "' + h(name) + '" must look like UTMN-1000 (a facility from the list, a dash, 1 to 5 digits)');
    else if (idx.names[name]) errors.push('the name ' + h(name) + ' already exists' + (idx.names[name] === 'trash' ? ' (in the trash)' : idx.names[name] === 'file' ? ' (earlier row in this file)' : ''));
  }

  var gcp = val('GCP & Ring'), vendor = val('Vendor'), eng = cleanPerson(x['TSU PAN Engineer']);
  if (gcp.length > 40) errors.push('GCP & Ring is longer than 40 characters');
  if (vendor.length > 30) errors.push('Vendor is longer than 30 characters');
  if (eng.length > 40) errors.push('TSU PAN Engineer is longer than 40 characters');
  var vMatch = CFG.vendors.filter(function (v) { return v.toLowerCase() === vendor.toLowerCase(); })[0];
  if (vMatch) vendor = vMatch;
  var gMatch = Object.keys(CFG.gcps).filter(function (g) { return g.toLowerCase() === gcp.toLowerCase(); })[0];
  if (gMatch) gcp = gMatch;

  var ips = {};
  ALLF.forEach(function (f) {
    var s = val(f); if (!s) return;
    if (s.length > 30) { errors.push(h(f) + ' is longer than 30 characters'); return; }
    if (IPF.indexOf(f) >= 0) {
      var c = canonIp(s);
      if (!c) { errors.push(h(f) + ' "' + h(s) + '" is not a valid IPv4 address (4 numbers from 0 to 255)'); return; }
      if (c !== s) warnings.push(h(f) + ' ' + h(s) + ' was read as ' + c);
      ips[f] = c;
    } else if (f === 'Subnet Mask') {
      if (maskBits(s) < 0) { errors.push('Subnet Mask "' + h(s) + '" is not a valid mask'); return; }
      ips[f] = canonIp(s);
    } else { // VLAN
      if (!/^\d{1,4}$/.test(s) || +s < 1 || +s > 4094) { errors.push(h(f) + ' "' + h(s) + '" must be a number from 1 to 4094'); return; }
      ips[f] = String(+s);
    }
  });
  if (!UNIQ.some(function (f) { return ips[f]; })) errors.push('no device IPs in this row (RTU, PLC, HMI or Moxa)');

  var mask = ips['Subnet Mask'] || CFG.mask, rowInfra = {};
  INFRA.forEach(function (f) { if (ips[f]) rowInfra[ips[f]] = f; });
  UNIQ.forEach(function (f) {
    if (!ips[f]) return;
    var edge = edgeAddress(ips[f], mask);
    if (edge) errors.push(h(f + ' ' + ips[f]) + ' is the ' + edge + ' address of its subnet');
    if (rowInfra[ips[f]]) errors.push(h(f + ' ' + ips[f]) + ' is the same as ' + h(rowInfra[ips[f]]));
  });
  var seen = {};
  UNIQ.forEach(function (f) {
    if (!ips[f]) return;
    var k = ips[f];
    if (seen[k]) errors.push(h(f + ' ' + k) + ' repeats ' + h(seen[k]) + ' of the same row');
    else if (idx.t[k]) errors.push(h(f + ' ' + k) + ' is already used by ' + h(idx.t[k]));
    else if (idx.inf[k]) errors.push(h(f + ' ' + k) + ' is a gateway or laptop address of ' + h(idx.inf[k]));
    seen[k] = f;
  });

  // non-blocking checks: imported data may come from older rules
  if (gcp && !CFG.gcps[gcp]) warnings.push('GCP & Ring ' + h(gcp) + ' is not configured, so this record can be edited but its IPs cannot be regenerated');
  if (vendor && CFG.vendors.indexOf(vendor) < 0) warnings.push('Vendor ' + h(vendor) + ' is not configured');
  if (configured(gcp, vendor) && !errors.length) {
    if (!ruleHost(gcp, vendor, ips)) warnings.push('the IPs do not follow the ' + h(gcp + ' / ' + vendor) + ' rule; they are kept as they are and stay reserved');
    var vl = CFG.vlan[gcp];
    if ((ips['RTU VLAN'] && ips['RTU VLAN'] !== vl[0]) || (ips['PLC VLAN'] && ips['PLC VLAN'] !== vl[1])) warnings.push('the VLANs differ from ' + h(gcp) + ' (' + vl.join(' / ') + ')');
  }
  if (ips['Gateway-1'] && ips['RTU IP-1'] && !sameSubnet(ips['Gateway-1'], ips['RTU IP-1'], mask)) warnings.push('RTU IP-1 is not in the same subnet as Gateway-1');

  var date = importDate(x['Date']);
  if (date && !isIsoDate(date)) warnings.push('Date "' + h(date) + '" is not YYYY-MM-DD; it is kept as text');

  if (errors.length) return { rec: null, errors: errors, warnings: warnings, name: name };
  return {
    rec: { name: name || 'UNKNOWN', gcp: gcp, vendor: vendor, engineer: eng, date: date, ips: ips },
    errors: [], warnings: warnings, name: name
  };
}
// Excel serial dates -> YYYY-MM-DD; other values are kept as text (max 20 characters)
function importDate(v) {
  if (typeof v === 'number' && v > 20000 && v < 80000) return new Date(Math.round((v - 25569) * 864e5)).toISOString().slice(0, 10);
  return String(v == null ? '' : v).trim().slice(0, 20);
}
function isIsoDate(s) {
  var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s); if (!m) return false;
  var d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  return d.getUTCFullYear() === +m[1] && d.getUTCMonth() === +m[2] - 1 && d.getUTCDate() === +m[3];
}

function rowOf(r) {
  var o = { 'Facility Name': r.name, 'GCP & Ring': r.gcp, 'Vendor': r.vendor, 'Date': r.date, 'TSU PAN Engineer': r.engineer };
  ALLF.forEach(function (f) { o[f] = r.ips[f] || ''; });
  return o;
}
