/* Settings (admin panel): GCP & Rings, address blocks, vendors, facilities, general. The server checks every change. */
var R = null;

init('settings').then(load);

function load() { return API.get('/admin/rules').then(function (r) { R = r; draw(); }, showErr); }
function done(text) { return function () { return load().then(function () { msg(text, 1); }); }; }
function fail(e) { showErr(e); window.scrollTo({ top: 0, behavior: REDUCED ? 'auto' : 'smooth' }); }
function formula(f) {
  if (!f.a) return String(f.b);
  return (f.a === 1 ? 'n' : f.a + 'n') + (f.b > 0 ? ' + ' + f.b : f.b < 0 ? ' − ' + (-f.b) : '');
}
function octs(o) { return Object.keys(o).sort().map(function (k) { return k + ' = ' + o[k]; }).join(', '); }
function vendorById(id) { return R.vendors.filter(function (v) { return v.id === id; })[0]; }
function netsOf(v) { var s = {}; v.fields.forEach(function (f) { s[f.net] = 1; }); return Object.keys(s).sort(); }
var NETNAME = { A: 'Network A', B: 'Network B', M: 'Moxa network' };

/* ---------- drawing ---------- */
function draw() {
  /* GCP & Rings with their blocks */
  var rows = R.gcps.map(function (g) {
    var rng = g.ranges.filter(function (x) { return x.vendor_active || x.blocks.length; });
    return rng.map(function (x, i) {
      var act = x.blocks.filter(function (b) { return b.status === 'active'; })[0], pl = x.blocks.filter(function (b) { return b.status === 'planned'; })[0];
      var retired = x.blocks.filter(function (b) { return b.status === 'retired'; });
      var c = x.state === 'full' ? 'full' : x.state === 'warn' ? 'warn' : '';
      var blockCell = act ? '<b>Block ' + act.seq + '</b> <span class="mut">' + esc(octs(act.octets)) + '</span>' + (retired.length ? '<br><small>' + retired.length + ' retired block(s): ' + esc(retired.map(function (b) { return octs(b.octets); }).join(' | ')) + ' (reserved)</small>' : '') : '<span class="warn">No active block</span>';
      var useCell = act ? '<div class="bar ' + c + '" style="min-width:90px"><i style="width:' + Math.round(100 * x.used / (x.max || 1)) + '%"></i></div><small class="' + c + '">' + x.used + ' / ' + x.max + (x.state === 'full' ? ' FULL' : '') + '</small>' : '';
      var nextCell = pl
        ? '<span class="chip w">Planned</span> <span class="mut">' + esc(octs(pl.octets)) + '</span><br><button class="sm primary" data-a="activate" data-id="' + pl.id + '" data-g="' + esc(g.code) + '" data-v="' + esc(x.vendor) + '">Activate now</button> <button class="sm ghost" data-a="rmblock" data-id="' + pl.id + '">Remove</button>'
        : '<button class="sm" data-a="addblock" data-g="' + g.id + '" data-v="' + x.vendor_id + '">' + (act ? 'Plan next block' : 'Add block') + '</button>';
      return '<tr' + (g.active ? '' : ' class="off"') + '>' + (i === 0 ? '<td rowspan="' + rng.length + '" class="rg"><b>' + esc(g.code) + '</b>' + (g.active ? '' : ' <span class="chip r">Disabled</span>') +
          '<small>' + g.octet1 + '.' + g.octet2 + '.x.x &middot; VLAN ' + esc(g.rtu_vlan) + ' / ' + esc(g.plc_vlan) + '</small>' +
          '<div class="row" style="margin-top:6px"><button class="sm" data-a="vlan" data-id="' + g.id + '">Edit VLAN</button><button class="sm ghost" data-a="gcptoggle" data-id="' + g.id + '">' + (g.active ? 'Disable' : 'Enable') + '</button></div></td>' : '') +
        '<td>' + esc(x.vendor) + (x.vendor_active ? '' : ' <span class="chip r">Disabled</span>') + '</td><td>' + blockCell + '</td><td>' + useCell + '</td><td>' + nextCell + '</td></tr>';
    }).join('');
  }).join('');
  var gcpP = '<section class="panel"><div class="panel-h"><h2>GCP &amp; Rings and address blocks</h2><button class="primary sm" id="addGcp">+ Add GCP &amp; Ring</button></div>' +
    '<p class="mut small">New facilities always come from the <b>active block</b>. When it is full, generation stops (no automatic overflow). Plan the next block ahead, prepare the network (gateway, VLAN, routing), then press <b>Activate now</b>: the old block is retired and its addresses stay reserved.</p>' +
    '<div class="tw auto"><table class="settings"><thead><tr><th>GCP &amp; Ring</th><th>Vendor</th><th>Active block (third octets)</th><th>Used</th><th>Next block</th></tr></thead><tbody>' +
    (rows || '<tr><td colspan="5" class="empty">No GCP &amp; Ring yet.</td></tr>') + '</tbody></table></div></section>';

  /* vendors */
  var vendP = '<section class="panel"><div class="panel-h"><h2>Vendors and address rules</h2><button class="primary sm" id="addVendor">+ Add vendor</button></div>' +
    '<p class="mut small">Each address is <code>host = a × n + b</code>, where n is the host number chosen by the tool. Rules cannot be edited after records exist; add a new vendor or a new block instead.</p>' +
    R.vendors.map(function (v) {
      return '<details class="vend"><summary><b>' + esc(v.name) + '</b>' + (v.active ? '' : ' <span class="chip r">Disabled</span>') + ' <span class="mut">' + v.capacity + ' host numbers per block &middot; default third octets ' + esc(octs(v.octets)) + '</span></summary>' +
        '<div class="vgrid">' + v.fields.map(function (f) { return '<div><span>' + esc(f.field) + '</span><code>' + esc(NETNAME[f.net] || f.net) + ' . ' + esc(formula(f)) + '</code></div>'; }).join('') + '</div>' +
        '<div class="row" style="margin-top:8px"><button class="sm ghost" data-a="ventoggle" data-id="' + v.id + '">' + (v.active ? 'Disable for new records' : 'Enable') + '</button></div></details>';
    }).join('') + '</section>';

  /* facilities + general */
  var facP = '<section class="panel"><div class="panel-h"><h2>Facilities</h2></div><p class="mut small">The first part of a facility name, for example <b>UTMN</b>-1000. Disabling hides it from new records; existing records keep their name.</p>' +
    '<div class="chips">' + R.facilities.map(function (f) { return '<span class="fchip' + (f.active ? '' : ' off') + '">' + esc(f.code) + '<button class="x" data-a="factoggle" data-id="' + f.id + '" title="' + (f.active ? 'Disable' : 'Enable') + ' ' + esc(f.code) + '">' + (f.active ? 'Disable' : 'Enable') + '</button></span>'; }).join('') + '</div>' +
    '<form class="row" id="facForm" style="margin-top:10px"><input id="facCode" maxlength="8" placeholder="New code, e.g. ABQQ" style="width:190px" aria-label="New facility code"><button class="sm primary" type="submit">Add facility</button></form></section>';
  var genP = '<section class="panel"><div class="panel-h"><h2>General</h2></div>' +
    '<form class="row" id="warnForm"><label for="warnAt" style="margin:0">Warn when a range is</label><input id="warnAt" inputmode="numeric" maxlength="2" value="' + R.settings.warn_at + '" style="width:64px"><span>% used or more</span><button class="sm primary" type="submit">Save</button></form>' +
    '<p class="mut small" style="margin:.8rem 0 .3rem">Subnet mask for generated records: <code>' + esc(R.settings.mask) + '</code></p>' +
    '<hr><h3 class="h3">Change the admin password</h3><form id="pwForm" class="grid2" autocomplete="off">' +
    '<div class="field"><label for="pw0">Current password</label><input id="pw0" type="password" autocomplete="current-password" maxlength="200"></div>' +
    '<div class="field"><label for="pw1">New password <small>(8+ characters)</small></label><input id="pw1" type="password" autocomplete="new-password" maxlength="200"></div>' +
    '<div><button class="sm primary" type="submit">Change password</button></div></form></section>';

  $('#set').innerHTML = gcpP + vendP + '<div class="dgrid half">' + facP + genP + '</div>';
  $('#addGcp').onclick = addGcp; $('#addVendor').onclick = addVendor;
  $('#facForm').onsubmit = addFacility; $('#warnForm').onsubmit = saveWarn; $('#pwForm').onsubmit = changePw;
}

document.addEventListener('click', function (e) {
  var b = e.target.closest && e.target.closest('#set button[data-a]'); if (!b) return;
  var id = +b.dataset.id;
  ({ vlan: editVlan, gcptoggle: toggleGcp, addblock: addBlock, activate: activateBlock, rmblock: removeBlock, ventoggle: toggleVendor, factoggle: toggleFacility })[b.dataset.a](id, b);
});

/* ---------- GCP & Ring ---------- */
function num(sel) { var v = $(sel).value.trim(); return /^\d+$/.test(v) ? +v : NaN; }
function addGcp() {
  var body = '<p class="mut small">Its first block is created automatically for every enabled vendor, using the vendor default third octets.</p><div class="grid2">' +
    '<div class="field" style="grid-column:1/-1"><label for="g_code">Code</label><input id="g_code" maxlength="40" placeholder="e.g. HDGCP2-R1"></div>' +
    '<div class="field"><label for="g_o1">Octet 1 <small>(GCP)</small></label><input id="g_o1" inputmode="numeric" maxlength="3" placeholder="e.g. 22"></div>' +
    '<div class="field"><label for="g_o2">Octet 2 <small>(Ring)</small></label><input id="g_o2" inputmode="numeric" maxlength="3" placeholder="e.g. 1"></div>' +
    '<div class="field"><label for="g_rv">RTU VLAN</label><input id="g_rv" inputmode="numeric" maxlength="4" placeholder="1 to 4094"></div>' +
    '<div class="field"><label for="g_pv">PLC VLAN</label><input id="g_pv" inputmode="numeric" maxlength="4" placeholder="1 to 4094"></div></div>' +
    '<small class="hint" id="g_prev"></small>';
  var data = function () { return { code: $('#g_code').value.trim().toUpperCase(), octet1: num('#g_o1'), octet2: num('#g_o2'), rtu_vlan: num('#g_rv'), plc_vlan: num('#g_pv') }; };
  var p = ask({ title: 'Add GCP & Ring', body: body, ok: 'Add', name: true, focus: '#g_code', check: function () {
    var d = data();
    if (d.code.length < 2) return 'Type the GCP &amp; Ring code.';
    if (!(d.octet1 >= 1 && d.octet1 <= 223) || !(d.octet2 >= 0 && d.octet2 <= 255)) return 'Octet 1 must be 1 to 223 and octet 2 must be 0 to 255.';
    if (!(d.rtu_vlan >= 1 && d.rtu_vlan <= 4094) || !(d.plc_vlan >= 1 && d.plc_vlan <= 4094)) return 'Both VLANs must be numbers from 1 to 4094.';
    return '';
  } });
  var keep = data;
  $('#dlg form').addEventListener('input', function () { var d = data(); $('#g_prev').textContent = d.octet1 >= 0 && d.octet2 >= 0 ? 'Addresses will look like ' + d.octet1 + '.' + d.octet2 + '.x.x' : ''; });
  var last = null; $('#dlg form').addEventListener('submit', function () { last = keep(); }, true);
  p.then(function (who) {
    if (!who) return;
    last.actor = who.name;
    API.post('/admin/gcps', last).then(done('GCP &amp; Ring <b>' + esc(last.code) + '</b> added with its first blocks.'), fail);
  });
}
function editVlan(id) {
  var g = R.gcps.filter(function (x) { return x.id === id; })[0];
  var body = '<p class="mut small">The new VLANs apply to records created from now on. Existing records keep the VLAN they were created with.</p><div class="grid2">' +
    '<div class="field"><label for="v_r">RTU VLAN</label><input id="v_r" inputmode="numeric" maxlength="4" value="' + esc(g.rtu_vlan) + '"></div>' +
    '<div class="field"><label for="v_p">PLC VLAN</label><input id="v_p" inputmode="numeric" maxlength="4" value="' + esc(g.plc_vlan) + '"></div></div>';
  var vals = null;
  ask({ title: 'VLANs of ' + g.code, body: body, ok: 'Save', name: true, focus: '#v_r', check: function () {
    vals = { rtu_vlan: num('#v_r'), plc_vlan: num('#v_p') };
    return vals.rtu_vlan >= 1 && vals.rtu_vlan <= 4094 && vals.plc_vlan >= 1 && vals.plc_vlan <= 4094 ? '' : 'Both VLANs must be numbers from 1 to 4094.';
  } }).then(function (who) {
    if (!who) return;
    vals.actor = who.name;
    API.patch('/admin/gcps/' + id, vals).then(done('VLANs of <b>' + esc(g.code) + '</b> saved.'), fail);
  });
}
function toggleGcp(id) {
  var g = R.gcps.filter(function (x) { return x.id === id; })[0];
  ask({ title: (g.active ? 'Disable ' : 'Enable ') + g.code + '?', ok: g.active ? 'Disable' : 'Enable', danger: g.active, name: true,
    body: g.active ? '<p>No new facility can be created in this GCP &amp; Ring. Existing records and their IPs are not changed and stay reserved.</p>' : '<p>New facilities can be created in this GCP &amp; Ring again.</p>' })
  .then(function (who) { if (who) API.patch('/admin/gcps/' + id, { active: !g.active, actor: who.name }).then(done('<b>' + esc(g.code) + '</b> ' + (g.active ? 'disabled' : 'enabled') + '.'), fail); });
}

/* ---------- blocks ---------- */
function addBlock(_, btn) {
  var g = R.gcps.filter(function (x) { return x.id === +btn.dataset.g; })[0], v = vendorById(+btn.dataset.v), nets = netsOf(v);
  var taken = []; g.ranges.forEach(function (x) { x.blocks.forEach(function (b) { Object.keys(b.octets).forEach(function (k) { taken.push(b.octets[k]); }); }); });
  var body = '<p>A new block of <b>' + v.capacity + '</b> host numbers for <b>' + esc(g.code + ' / ' + v.name) + '</b>. Addresses will be ' + g.octet1 + '.' + g.octet2 + '.<i>third octet</i>.host.</p>' +
    '<div class="grid2">' + nets.map(function (n) { return '<div class="field"><label for="b_' + n + '">' + NETNAME[n] + ' <small>third octet</small></label><input id="b_' + n + '" inputmode="numeric" maxlength="3" placeholder="0 to 255"></div>'; }).join('') + '</div>' +
    '<div class="note">Already used in ' + esc(g.code) + ' (cannot be chosen): <b>' + esc(taken.sort(function (a, b) { return a - b; }).join(', ') || 'none') + '</b></div>' +
    '<div class="note warn">The block stays <b>planned</b> and is not used until you activate it. Prepare the network for these octets first.</div>';
  var octets = null;
  ask({ title: 'Plan the next block', body: body, ok: 'Save planned block', name: true, focus: '#b_' + nets[0], check: function () {
    octets = {}; var bad = '';
    nets.forEach(function (n) { var x = num('#b_' + n); if (!(x >= 0 && x <= 255)) bad = 'Type a third octet from 0 to 255 for every network.'; else if (taken.indexOf(x) >= 0) bad = 'Third octet ' + x + ' is already used in this GCP &amp; Ring.'; octets[n] = x; });
    var vals = nets.map(function (n) { return octets[n]; });
    if (!bad && vals.some(function (x, i) { return vals.indexOf(x) !== i; })) bad = 'Each network needs its own third octet.';
    return bad;
  } }).then(function (who) {
    if (who) API.post('/admin/blocks', { gcp_id: g.id, vendor_id: v.id, octets: octets, actor: who.name }).then(done('Block saved for <b>' + esc(g.code + ' / ' + v.name) + '</b>.'), fail);
  });
}
function activateBlock(id, btn) {
  ask({ title: 'Activate the next block?', ok: 'Activate now', name: true,
    body: '<p>From now on, new facilities in <b>' + esc(btn.dataset.g + ' / ' + btn.dataset.v) + '</b> get addresses from the new block.</p>' +
      '<p>The current block is <b>retired</b>: its records and addresses stay exactly as they are and stay reserved, but free numbers left in it are no longer given out.</p>' +
      '<div class="note warn">This cannot be undone. Make sure the gateway, VLAN and routing for the new third octets are ready in the field.</div>' })
  .then(function (who) { if (who) API.post('/admin/blocks/' + id + '/activate', { actor: who.name }).then(done('The new block is active.'), fail); });
}
function removeBlock(id) {
  ask({ title: 'Remove the planned block?', ok: 'Remove', danger: true, name: true, body: '<p>The planned block was never used, so nothing else changes. Its third octets become free to plan again.</p>' })
  .then(function (who) { if (who) API.del('/admin/blocks/' + id, { actor: who.name }).then(done('Planned block removed.'), fail); });
}

/* ---------- vendors ---------- */
function toggleVendor(id) {
  var v = vendorById(id);
  ask({ title: (v.active ? 'Disable ' : 'Enable ') + v.name + '?', ok: v.active ? 'Disable' : 'Enable', danger: v.active, name: true,
    body: v.active ? '<p>No new facility can be created with this vendor. Existing records are not changed.</p>' : '<p>New facilities can use this vendor again.</p>' })
  .then(function (who) { if (who) API.patch('/admin/vendors/' + id, { active: !v.active, actor: who.name }).then(done('<b>' + esc(v.name) + '</b> ' + (v.active ? 'disabled' : 'enabled') + '.'), fail); });
}
function addVendor() {
  var tpl = {}; (R.vendors[0] ? R.vendors[0].fields : []).forEach(function (f) { tpl[f.field] = f; });
  var rows = R.ip_fields.map(function (f, i) {
    var t = tpl[f], infra = R.infra_fields.indexOf(f) >= 0;
    return '<tr><td><label class="check"><input type="checkbox" id="vf_on' + i + '"' + (t ? ' checked' : '') + '>' + esc(f) + '</label></td>' +
      '<td><select id="vf_net' + i + '" aria-label="Network of ' + esc(f) + '">' + R.nets.map(function (n) { return '<option value="' + n + '"' + (t && t.net === n ? ' selected' : '') + '>' + NETNAME[n] + '</option>'; }).join('') + '</select></td>' +
      '<td>' + (infra ? '<span class="mut">fixed</span><input type="hidden" id="vf_a' + i + '" value="0">' : '<input id="vf_a' + i + '" inputmode="numeric" maxlength="3" value="' + (t ? t.a : 1) + '" aria-label="a of ' + esc(f) + '">') + '</td>' +
      '<td><input id="vf_b' + i + '" maxlength="4" value="' + (t ? t.b : 0) + '" aria-label="b of ' + esc(f) + '"></td></tr>';
  }).join('');
  var body = '<p class="mut small">Describe how the vendor numbers its devices. Each address is <code>host = a × n + b</code> on one of the networks. The form starts with a copy of the first vendor; change what differs.</p>' +
    '<div class="grid2"><div class="field"><label for="vn">Vendor name</label><input id="vn" maxlength="30" placeholder="e.g. Emerson"></div>' +
    '<div class="field"><label for="vc">Host numbers per block <small>(capacity)</small></label><input id="vc" inputmode="numeric" maxlength="3" placeholder="e.g. 39"></div></div>' +
    '<fieldset><legend>Default third octets</legend><div class="grid3">' + R.nets.map(function (n) { return '<div class="field"><label for="vo' + n + '">' + NETNAME[n] + '</label><input id="vo' + n + '" inputmode="numeric" maxlength="3" placeholder="0 to 255"></div>'; }).join('') + '</div>' +
    '<small class="hint">Used for the first block of every GCP &amp; Ring. They must not be used by another vendor.</small></fieldset>' +
    '<div class="tw auto" style="max-height:250px"><table class="settings"><thead><tr><th>Field</th><th>Network</th><th>a (× n)</th><th>b</th></tr></thead><tbody>' + rows + '</tbody></table></div>' +
    '<div class="row"><button type="button" id="vcheck">Check the rule</button><small>Shows the addresses of the first and last host number.</small></div><div id="vres"></div>';
  function data() {
    var fields = [], octets = {};
    R.ip_fields.forEach(function (f, i) {
      if (!$('#vf_on' + i).checked) return;
      fields.push({ field: f, net: $('#vf_net' + i).value, a: parseInt($('#vf_a' + i).value, 10), b: parseInt($('#vf_b' + i).value, 10) });
    });
    R.nets.forEach(function (n) { var x = num('#vo' + n); if (fields.some(function (f) { return f.net === n; })) octets[n] = x; });
    return { name: cleanPerson($('#vn').value), capacity: num('#vc'), octets: octets, fields: fields };
  }
  function localErr(d) {
    if (d.name.length < 2) return 'Type the vendor name.';
    if (!(d.capacity >= 1 && d.capacity <= 254)) return 'Capacity must be a number from 1 to 254.';
    if (d.fields.some(function (f) { return isNaN(f.a) || isNaN(f.b); })) return 'a and b must be whole numbers.';
    for (var k in d.octets) if (!(d.octets[k] >= 0 && d.octets[k] <= 255)) return 'Give a third octet from 0 to 255 for ' + NETNAME[k] + '.';
    return '';
  }
  var checked = '', last = null;
  function check() {
    var d = data(), le = localErr(d);
    if (le) { $('#vres').innerHTML = '<div class="note warn">' + le + '</div>'; return; }
    API.post('/admin/vendors/check', d).then(function (r) {
      if (!r.ok) { checked = ''; $('#vres').innerHTML = '<div class="note warn"><b>' + esc(r.message) + '</b>' + (r.errors.length ? '<ul>' + r.errors.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>' : '') + '</div>'; return; }
      checked = JSON.stringify(d);
      var fields = Object.keys(r.sample[0].ips);
      $('#vres').innerHTML = '<div class="note info">The rule is safe: no address repeats, none leaves 1 to 254, none hits a gateway or the laptop. Example for 10.1.x.x:</div>' +
        '<div class="tw auto" style="max-height:200px;margin-top:6px"><table class="diff"><thead><tr><th>Field</th>' + r.sample.map(function (s) { return '<th>host ' + s.n + '</th>'; }).join('') + '</tr></thead><tbody>' +
        fields.map(function (f) { return '<tr><td>' + esc(f) + '</td>' + r.sample.map(function (s) { return '<td class="ip">' + esc(s.ips[f] || '-') + '</td>'; }).join('') + '</tr>'; }).join('') + '</tbody></table></div>';
    }, function (e) { $('#vres').innerHTML = '<div class="note warn">' + errHtml(e) + '</div>'; });
  }
  var p = ask({ title: 'Add vendor', body: body, ok: 'Add vendor', wide: true, name: true, focus: '#vn', check: function () {
    var d = data(), le = localErr(d);
    if (le) return le;
    if (checked !== JSON.stringify(d)) { check(); return 'Press <b>Check the rule</b> and review the example addresses first. If it is safe, press Add vendor again.'; }
    last = d; return '';
  } });
  $('#vcheck').onclick = check;
  p.then(function (who) {
    if (!who) return;
    last.actor = who.name;
    API.post('/admin/vendors', last).then(done('Vendor <b>' + esc(last.name) + '</b> added with a first block in every GCP &amp; Ring.'), fail);
  });
}

/* ---------- facilities, general ---------- */
function addFacility(e) {
  e.preventDefault();
  var code = $('#facCode').value.trim().toUpperCase();
  if (!/^[A-Z][A-Z0-9]{1,7}$/.test(code)) return msg('A facility code must be 2 to 8 capital letters or digits, starting with a letter (for example UTMN).');
  ask({ title: 'Add facility ' + code + '?', ok: 'Add', name: true, body: '<p>New records can then be named <b>' + esc(code) + '-1000</b>, <b>' + esc(code) + '-1001</b>, ...</p>' })
  .then(function (who) { if (who) API.post('/admin/facilities', { code: code, actor: who.name }).then(done('Facility <b>' + esc(code) + '</b> added.'), fail); });
}
function toggleFacility(id) {
  var f = R.facilities.filter(function (x) { return x.id === id; })[0];
  ask({ title: (f.active ? 'Disable ' : 'Enable ') + f.code + '?', ok: f.active ? 'Disable' : 'Enable', danger: f.active, name: true,
    body: f.active ? '<p>' + esc(f.code) + ' is hidden from new records. Existing records keep their name.</p>' : '<p>' + esc(f.code) + ' can be used for new records again.</p>' })
  .then(function (who) { if (who) API.patch('/admin/facilities/' + id, { active: !f.active, actor: who.name }).then(done('Facility <b>' + esc(f.code) + '</b> ' + (f.active ? 'disabled' : 'enabled') + '.'), fail); });
}
function saveWarn(e) {
  e.preventDefault();
  var v = num('#warnAt');
  if (!(v >= 50 && v <= 99)) return msg('The warning level must be a number from 50 to 99.');
  ask({ title: 'Warn at ' + v + '%?', ok: 'Save', name: true, body: '<p>Ranges at or above ' + v + '% are shown in orange on the dashboard and in the generation preview.</p>' })
  .then(function (who) { if (who) API.patch('/admin/settings', { warn_at: v, actor: who.name }).then(done('Warning level saved.'), fail); });
}
function changePw(e) {
  e.preventDefault();
  var cur = $('#pw0').value, nw = $('#pw1').value;
  if (!cur || nw.length < 8) return msg('Type the current password and a new password of at least 8 characters.');
  API.post('/auth/password', { current: cur, new: nw }).then(function () { $('#pw0').value = ''; $('#pw1').value = ''; msg('The admin password was changed. Tell the other engineers.', 1); window.scrollTo(0, 0); }, fail);
}
