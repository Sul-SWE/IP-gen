/* Self-tests for the engine. Open test.html to run them. The first 14 are the original prototype tests. */
function runTests() {
  var T = [], t = function (n, ok, d) { T.push([n, !!ok, d || '']); }, id = 1, r;

  /* ----- original 14 ----- */
  r = build('HDGCP1-R1', 'Yokogawa', 1);
  t('Hand-checked Yokogawa n=1: RTU 18.1.20.169 / 18.1.21.169', r['RTU IP-1'] === '18.1.20.169' && r['RTU IP-2'] === '18.1.21.169');
  t('Hand-checked Yokogawa n=1: PLC .85, Internal .1, HMI .211, Moxa 18.1.10.1', r['PLC IP-1'] === '18.1.20.85' && r['PLC IP-2'] === '18.1.21.85' && r['RTU Internal IP-1'] === '18.1.20.1' && r['RTU-HMI IP'] === '18.1.20.211' && r['IES Moxa IP'] === '18.1.10.1');
  r = build('SHGCP1-R1', 'Honeywell', 1);
  t('Hand-checked Honeywell k=1: RTU 19.1.100.1, PLC-2 .4, HMI 19.1.101.1', r['RTU IP-1'] === '19.1.100.1' && r['PLC IP-2'] === '19.1.100.4' && r['RTU-HMI IP'] === '19.1.101.1');
  t('Honeywell has no RTU Internal fields', !('RTU Internal IP-1' in r));
  var recs = [], full = [];
  Object.keys(CFG.gcps).forEach(function (g) {
    CFG.vendors.forEach(function (v) {
      for (var i = 0; i < CFG.max[v]; i++) { var a = allocate(g, v, recs); if (a.full) { full.push(g + v + ' early'); break; } recs.push({ id: id++, name: 'T-' + id, gcp: g, vendor: v, ips: a.ips, del: false }); }
      if (!allocate(g, v, recs).full) full.push(g + v + ' not full');
    });
  });
  t('Every range fills to its limit and then stops (no overflow)', full.length === 0, full.join(', '));
  var seen = {}, dup = 0, bad = 0, cnt = 0;
  recs.forEach(function (x) {
    UNIQ.forEach(function (f) {
      var ip = x.ips[f]; if (!ip) return; cnt++; if (seen[ip]) dup++; seen[ip] = 1;
      var o = ip.split('.').map(Number); if (o.length !== 4 || o.some(function (y) { return y < 0 || y > 255; }) || o[3] < 1 || o[3] > 249) bad++;
    });
  });
  t('No duplicate IP across ' + cnt + ' generated addresses (all GCPs and vendors)', dup === 0, dup + ' duplicates');
  t('All hosts valid and never touch .250 / .253', bad === 0, bad + ' bad');
  var g = 'HDGCP1-R1', y = recs.filter(function (x) { return x.gcp === g && x.vendor === 'Yokogawa'; }), five = y[4];
  var rest = recs.filter(function (x) { return x !== five; }), a = allocate(g, 'Yokogawa', rest);
  t('A freed number (permanent delete) is reused first', a.n === 5);
  var tr = recs.map(function (x) { return x === five ? Object.assign({}, x, { del: true }) : x; });
  t('A deleted record in the trash keeps its numbers reserved', allocate(g, 'Yokogawa', tr).full === true);
  var base = [{ id: 1, name: 'UTMN-1', ips: { 'RTU IP-1': build('HDGCP1-R1', 'Yokogawa', 1)['RTU IP-1'] }, del: false }], s = allocate('HDGCP1-R1', 'Yokogawa', base);
  t('An IP already used (e.g. imported) makes the tool skip that number', s.n === 2 && s.skipped[0] === 1);
  t('Same GCP and vendor in Ring 2 does not clash (different octet 2)', (function () { CFG.gcps['X-R2'] = [18, 2]; CFG.vlan['X-R2'] = ['1', '2']; var q = allocate('X-R2', 'Yokogawa', base); delete CFG.gcps['X-R2']; delete CFG.vlan['X-R2']; return q.n === 1; })());
  var nm = [{ id: 1, name: 'UTMN-1000' }];
  t('Duplicate name is rejected (even with different letter case)', checkName('utmn-1000', nm) !== '' && checkName('UTMN-1001', nm) === '');
  t('Bad name formats are rejected', checkName('UTMN', nm) !== '' && checkName('ABCD-12', nm) !== '' && checkName('UTMN-12ab', nm) !== '' && checkName('UTMN-123456', nm) !== '');
  t('Editing a record does not clash with itself', checkName('UTMN-1000', nm, 1) === '');

  /* ----- new: addresses ----- */
  t('IPv4 parsing: leading zeros normalised, octet 256 rejected', canonIp('018.001.020.07') === '18.1.20.7' && canonIp('18.1.20.256') === null && canonIp('18.1.20') === null && canonIp('a.b.c.d') === null);
  t('Subnet mask: /24 valid, non-contiguous mask invalid', maskBits('255.255.255.0') === 24 && maskBits('255.0.255.0') === -1 && maskBits('255.255.255.256') === -1);
  t('Network and broadcast addresses are detected (/24)', edgeAddress('18.1.20.0', '255.255.255.0') === 'network' && edgeAddress('18.1.20.255', '255.255.255.0') === 'broadcast' && edgeAddress('18.1.20.1', '255.255.255.0') === '');
  t('Rule check finds the host number of generated IPs', ruleHost('HDGCP1-R1', 'Yokogawa', build('HDGCP1-R1', 'Yokogawa', 7)) === 7 && ruleHost('HDGCP1-R1', 'Honeywell', build('HDGCP1-R1', 'Yokogawa', 7)) === 0);
  var gw = [{ id: 1, name: 'USED', ips: { 'Gateway-1': '18.1.20.169' }, del: false }];
  t('Allocation skips a host whose IP is a gateway/laptop address of another record', allocate('HDGCP1-R1', 'Yokogawa', gw).n === 2);
  var lz = [{ id: 1, name: 'UTMN-5', ips: { 'RTU IP-1': '018.001.020.169' }, del: false }];
  t('Old data with leading zeros still blocks the same address', allocate('HDGCP1-R1', 'Yokogawa', lz).n === 2);

  /* ----- new: people ----- */
  t('Engineer name: trimmed, inner spaces collapsed, 2-40 letters', cleanPerson('  Eng   A  ') === 'Eng A' && checkPerson('Eng A') === '' && checkPerson('E') !== '' && checkPerson('<b>x</b>') !== '' && checkPerson('12345') !== '');

  /* ----- new: import rows ----- */
  var row = function (n, extra) { var o = rowOf({ name: 'UTMN-' + n, gcp: 'HDGCP1-R1', vendor: 'Yokogawa', date: '2026-01-02', engineer: 'Eng A', ips: build('HDGCP1-R1', 'Yokogawa', n) }); for (var k in extra || {}) o[k] = extra[k]; return o; };
  var run = function (rows, existing) { var idx = makeIndex(existing || []); return rows.map(function (x) { var r = checkImportRow(x, idx); if (r.rec) indexAdd(idx, r.rec); return r; }); };
  var ex = [{ id: 1, name: 'UTMN-1', gcp: 'HDGCP1-R1', vendor: 'Yokogawa', ips: build('HDGCP1-R1', 'Yokogawa', 1), del: false },
            { id: 2, name: 'UTMN-2', gcp: 'HDGCP1-R1', vendor: 'Yokogawa', ips: build('HDGCP1-R1', 'Yokogawa', 2), del: true }];
  var res = run([row(3)], ex);
  t('Import: a clean row following the rule is accepted without notes', !!res[0].rec && res[0].warnings.length === 0, res[0].errors.concat(res[0].warnings).join('; '));
  res = run([row(9, { 'Facility Name': 'UTMN-1' })], ex);
  t('Import: name of an active record is rejected', !res[0].rec);
  res = run([row(9, { 'Facility Name': 'utmn-2' })], ex);
  t('Import: name of a record in the trash is rejected', !res[0].rec && /trash/.test(res[0].errors.join()));
  res = run([row(2, { 'Facility Name': 'UTMN-50' })], ex);
  t('Import: IPs of a record in the trash are rejected', !res[0].rec && /already used/.test(res[0].errors.join()));
  res = run([row(9, { 'Facility Name': 'UTMN-60', 'RTU IP-1': ex[0].ips['PLC IP-1'] })], ex);
  t('Import: an IP used in a different column is rejected (cross-column)', !res[0].rec);
  res = run([row(10), row(10, { 'Facility Name': 'UTMN-61' })]);
  t('Import: duplicate of an earlier row in the same file is rejected', !!res[0].rec && !res[1].rec);
  res = run([row(10, { 'PLC IP-1': '18.1.20.178' })]);
  t('Import: the same IP twice inside one row is rejected', !res[0].rec && /same row/.test(res[0].errors.join()));
  res = run([row(11, { 'RTU IP-1': '18.1.20.300' })]);
  t('Import: octet above 255 is rejected', !res[0].rec);
  res = run([row(12, { 'RTU IP-1': '18.1.20.253' })]);
  t('Import: a device IP equal to the gateway is rejected', !res[0].rec && /same as Gateway-1/.test(res[0].errors.join()));
  res = run([row(13, { 'RTU-HMI IP': '18.1.20.0' })]);
  t('Import: network address (.0) as a device IP is rejected', !res[0].rec && /network address/.test(res[0].errors.join()));
  res = run([row(14, { 'RTU VLAN': '5000' })]);
  t('Import: VLAN outside 1-4094 is rejected', !res[0].rec);
  res = run([row(15, { 'Subnet Mask': '255.0.255.0' })]);
  t('Import: invalid subnet mask is rejected', !res[0].rec);
  var used = function (n) { var o = {}; ['Facility Name', 'RTU IP-1'].forEach(function (k) { o[k] = ''; }); o['Facility Name'] = 'Used'; o['RTU IP-1'] = '30.1.1.' + n; return o; };
  res = run([used(1), used(2)]);
  t('Import: placeholder names (Used) may repeat', !!res[0].rec && !!res[1].rec);
  res = run([row(16, { 'RTU IP-1': '18.1.20.017' })]);
  t('Import: leading zeros are normalised and noted', !!res[0].rec && res[0].rec.ips['RTU IP-1'] === '18.1.20.17' && res[0].warnings.length > 0);
  res = run([row(17, { 'RTU IP-1': '18.1.20.5' })]);
  t('Import: IPs that do not follow the rule are kept, with a note', !!res[0].rec && /do not follow/.test(res[0].warnings.join()));
  res = run([row(18, { 'GCP & Ring': 'OLDGCP-R9' })]);
  t('Import: unconfigured GCP is allowed, with a note', !!res[0].rec && /not configured/.test(res[0].warnings.join()));
  var file = [row(20), row(21), row(22)], first = run(file), stored = first.filter(function (r) { return r.rec; }).map(function (r, i) { var x = r.rec; x.id = 100 + i; x.del = false; return x; });
  var second = run(file, stored);
  t('Import: the same file twice adds nothing the second time', first.every(function (r) { return r.rec; }) && second.every(function (r) { return !r.rec; }));
  var round = run(stored.map(rowOf));
  t('Import: an exported file imports cleanly into an empty system', round.every(function (r) { return r.rec && !r.warnings.length; }));
  t('Import: Excel serial date becomes YYYY-MM-DD', importDate(46000) === '2025-12-09' && importDate('04/11/2026') === '04/11/2026');
  res = run([row(23, { 'Facility Name': '<img src=x onerror=alert(1)>' })]);
  t('Import: markup in a cell is rejected and escaped in the message', !res[0].rec && res[0].errors.join().indexOf('<img') < 0);

  return T;
}
