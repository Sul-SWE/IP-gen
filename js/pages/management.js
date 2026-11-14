/* IP Management: records, trash and change log. All data comes from the server, page by page. */
var cur = 'active', openIds = {}, items = [], page = 1, pages = 1, total = 0, loadSeq = 0;
var FIELDS = [['all', 'All fields'], ['name', 'Name'], ['gcp', 'GCP & Ring'], ['vendor', 'Vendor'], ['engineer', 'Engineer'], ['ip', 'IP']];

init('management').then(function () {
  $('#crit').innerHTML = FIELDS.map(function (f) { return '<option value="' + f[0] + '">' + esc(f[1]) + '</option>'; }).join('');
  ['active', 'trash', 'log'].forEach(function (k) { $('#t_' + k).onclick = function () { tab(k); }; });
  $('#q').oninput = debounce(function () { load(true); }, 250);
  $('#crit').onchange = function () { load(true); };
  $('#t').addEventListener('click', onTableClick);
  tab(fromHash());
});
function fromHash() { return location.hash === '#log' ? 'log' : location.hash === '#trash' ? 'trash' : 'active'; }
window.addEventListener('hashchange', function () { if (CFG && fromHash() !== cur) tab(fromHash()); });

function tab(x) {
  cur = x; openIds = {};
  ['active', 'trash', 'log'].forEach(function (k) { var b = $('#t_' + k); b.classList.toggle('on', k === x); b.setAttribute('aria-selected', k === x); });
  $('#critBox').hidden = x === 'log';
  $('#q').placeholder = x === 'log' ? 'Engineer, action, facility, details...' : 'Name, IP, GCP, vendor, engineer...';
  history.replaceState(null, '', x === 'active' ? location.pathname : '#' + x);
  load(true);
}
function setCounts(c) {
  $('#t_active').innerHTML = 'Records <span class="n">' + c.active + '</span>';
  $('#t_trash').innerHTML = 'Trash <span class="n">' + c.trash + '</span>';
  $('#t_log').innerHTML = 'Change log <span class="n">' + c.log + '</span>';
}

/* ---------- loading ---------- */
function load(reset) {
  if (reset) { page = 1; items = []; }
  var seq = ++loadSeq, q = encodeURIComponent($('#q').value.trim());
  var url = cur === 'log' ? '/audit-log?q=' + q + '&page=' + page
    : '/records?status=' + cur + '&q=' + q + '&field=' + $('#crit').value + '&page=' + page + '&size=100&sort=new';
  return API.get(url).then(function (r) {
    if (seq !== loadSeq) return;               // a newer search is on its way
    items = reset ? r.items : items.concat(r.items);
    pages = r.pages; total = r.total; setCounts(r.counts); draw();
  }, function (e) { if (seq === loadSeq) showErr(e); });
}
function reload() { return load(true); }

/* ---------- drawing ---------- */
function td(l, v, cls) { return '<td data-l="' + esc(l) + '"' + (cls ? ' class="' + cls + '"' : '') + '>' + (v ? esc(v) : '<span class="mut">-</span>') + '</td>'; }
function ipGrid(r) {
  var meta = esc(r.name) + ' &middot; ' + esc(r.gcp || '-') + ' / ' + esc(r.vendor || '-') +
    (r.host ? ' &middot; host ' + r.host : r.imported ? ' &middot; <span class="warn">imported: IPs do not follow a current rule</span>' : '') +
    ' &middot; created ' + esc(r.created_at) + (r.updated_at !== r.created_at ? ' &middot; changed ' + esc(r.updated_at) : '');
  return '<div class="mut" style="font-size:.78rem;margin-bottom:6px">' + meta + '</div><div class="ipgrid">' +
    Object.keys(r.ips).map(function (f) { return '<div><span>' + esc(f) + '</span><code>' + esc(r.ips[f]) + '</code></div>'; }).join('') + '</div>';
}
function draw() {
  var q = $('#q').value.trim();
  $('#more').innerHTML = page < pages ? '<button class="sm" id="moreBtn">Show more</button>' : '';
  if (page < pages) $('#moreBtn').onclick = function () { page++; load(false); };
  if (cur === 'log') {
    $('#count').textContent = items.length + ' of ' + total + ' entries';
    $('#tnote').textContent = 'Newest first. The change log cannot be edited.';
    $('#t').innerHTML = '<thead><tr><th>Time</th><th>Engineer</th><th>Action</th><th>Facility</th><th>Details</th></tr></thead><tbody>' +
      (items.map(function (l) {
        return '<tr>' + td('Time', l.at) + td('Engineer', l.who) + '<td data-l="Action">' + chip(l.action) + '</td>' + td('Facility', l.name) + '<td data-l="Details" style="white-space:normal;min-width:260px">' + esc(l.details) + '</td></tr>';
      }).join('') || '<tr><td colspan="5" class="empty">' + (q ? 'No entries match your search.' : 'No changes recorded yet.') + '</td></tr>') + '</tbody>';
    return;
  }
  var trash = cur === 'trash', cols = trash ? 7 : 8;
  $('#count').textContent = items.length + ' of ' + total + ' shown';
  $('#tnote').innerHTML = trash ? 'Records in the trash keep their name and IPs reserved. <b>Delete forever</b> frees them.' : 'Click <b>IPs</b> to see all addresses of a record.';
  var head = trash
    ? '<th>Facility Name</th><th>GCP &amp; Ring</th><th>Vendor</th><th>Deleted on</th><th>Deleted by</th><th>RTU IP-1</th><th></th>'
    : '<th>Facility Name</th><th>GCP &amp; Ring</th><th>Vendor</th><th>Date</th><th>Engineer</th><th>RTU IP-1</th><th>PLC IP-1</th><th></th>';
  $('#t').innerHTML = '<thead><tr>' + head + '</tr></thead><tbody>' + (items.map(function (r) {
    var id = +r.id, cells = trash
      ? td('Facility', r.name) + td('GCP & Ring', r.gcp) + td('Vendor', r.vendor) + td('Deleted on', r.deleted_at) + td('Deleted by', r.deleted_by) + td('RTU IP-1', r.ips['RTU IP-1'], 'ip')
      : td('Facility', r.name) + td('GCP & Ring', r.gcp) + td('Vendor', r.vendor) + td('Date', r.date) + td('Engineer', r.engineer) + td('RTU IP-1', r.ips['RTU IP-1'], 'ip') + td('PLC IP-1', r.ips['PLC IP-1'], 'ip');
    var acts = '<button class="sm ghost" data-a="ips" data-id="' + id + '" aria-expanded="' + !!openIds[id] + '">IPs ' + (openIds[id] ? '&#9652;' : '&#9662;') + '</button>' + (trash
      ? '<button class="sm" data-a="restore" data-id="' + id + '">Restore</button><button class="sm danger" data-a="purge" data-id="' + id + '">Delete forever</button>'
      : '<button class="sm" data-a="edit" data-id="' + id + '">Modify</button><button class="sm danger" data-a="del" data-id="' + id + '">Delete</button>');
    return '<tr>' + cells + '<td class="act">' + acts + '</td></tr>' + (openIds[id] ? '<tr class="detail"><td colspan="' + cols + '">' + ipGrid(r) + '</td></tr>' : '');
  }).join('') || '<tr><td colspan="' + cols + '" class="empty">' + (q ? 'No records match your search.' : trash ? 'The trash is empty.' : 'No records yet. <a href="generate.html">Create the first one</a>.') + '</td></tr>') + '</tbody>';
}

/* ---------- actions ---------- */
function onTableClick(e) {
  var b = e.target.closest('button[data-a]'); if (!b) return;
  var id = +b.dataset.id, a = b.dataset.a, r = items.filter(function (x) { return x.id === id; })[0];
  if (!r) return;
  if (a === 'ips') { openIds[id] = !openIds[id]; return draw(); }
  ({ edit: edit, del: del, restore: restore, purge: purge })[a](r);
}
// the server works on the newest data; if this record changed elsewhere it answers 409 and the list is refreshed
function run(promise, okHtml) {
  return promise.then(function (res) { return reload().then(function () { msg(okHtml(res), 1); fillEngineerList(); }); },
    function (e) { return reload().then(function () { showErr(e); }); });
}

function del(r) {
  ask({ title: 'Move ' + r.name + ' to the trash?', danger: true, ok: 'Move to trash', name: true,
    body: '<p>The record leaves the active list. Its name and IPs <b>stay reserved</b> until it is deleted forever, so they cannot be given to another facility.</p><p class="mut">You can restore it from the Trash tab.</p>' })
  .then(function (who) {
    if (who) run(API.del('/records/' + r.id, { actor: who.name, version: r.version }), function (x) { return '<b>' + esc(x.name) + '</b> moved to the trash. Its IPs stay reserved.'; });
  });
}
function restore(r) {
  ask({ title: 'Restore ' + r.name + '?', ok: 'Restore', name: true, body: '<p>The record goes back to the active list with the same name and IPs.</p>' })
  .then(function (who) {
    if (who) run(API.post('/records/' + r.id + '/restore', { actor: who.name, version: r.version }), function (x) { return '<b>' + esc(x.name) + '</b> restored.'; });
  });
}
function purge(r) {
  ask({ title: 'Delete ' + r.name + ' forever?', danger: true, ok: 'Delete forever', name: true,
    body: '<p>This cannot be undone. The record is removed and its name and IPs <b>become free</b>: the next new facility in ' + esc((r.gcp || '-') + ' / ' + (r.vendor || '-')) + ' may get them.</p>' +
      '<div class="note warn">Only do this when the devices with these addresses no longer exist in the field.</div>' })
  .then(function (who) {
    if (who) run(API.del('/records/' + r.id + '/permanent', { actor: who.name, version: r.version }), function (x) { return '<b>' + esc(x.name) + '</b> deleted forever. Its IPs are free again.'; });
  });
}

/* ----- Modify ----- */
function edit(r0) {
  var m = /^([A-Z][A-Z0-9]{1,7})-(\d{1,5})$/.exec(String(r0.name).toUpperCase()), std = !!m, parts = std ? [m[1], m[2]] : ['', ''];
  var facOpts = CFG.facilities.slice(); if (std && facOpts.indexOf(parts[0]) < 0) facOpts.push(parts[0]);
  var gcpOpts = CFG.gcps.slice(); if (r0.gcp && gcpOpts.indexOf(r0.gcp) < 0) gcpOpts.push(r0.gcp);
  var venOpts = CFG.vendors.slice(); if (r0.vendor && venOpts.indexOf(r0.vendor) < 0) venOpts.push(r0.vendor);
  var body =
    '<p class="mut" style="font-size:.84rem">Editing <b>' + esc(r0.name) + '</b>. Change only what you need.</p>' +
    '<fieldset><legend>Facility name</legend><div class="grid2">' +
      '<div class="field"><label for="e_fac">Facility</label><select id="e_fac">' + options(facOpts, parts[0], std ? null : 'Keep "' + r0.name + '"') + '</select></div>' +
      '<div class="field"><label for="e_num">Well number</label><input id="e_num" inputmode="numeric" maxlength="5" value="' + esc(parts[1]) + '"' + (std ? '' : ' placeholder="empty = keep"') + '></div>' +
    '</div><small class="hint" id="e_nmh"></small>' +
    (std ? '' : '<div class="note info">This record has the imported placeholder name <b>' + esc(r0.name || '(empty)') + '</b>. Leave both fields empty to keep it, or choose a facility and well number to give it a real name.</div>') +
    '</fieldset>' +
    '<fieldset><legend>Record details</legend><div class="grid2">' +
      '<div class="field"><label for="e_eng">Engineer on record</label><input id="e_eng" list="engList" maxlength="40" value="' + esc(r0.engineer || '') + '" autocomplete="off"></div>' +
      '<div class="field"><label for="e_date">Date <small>(YYYY-MM-DD)</small></label><input id="e_date" inputmode="numeric" maxlength="20" placeholder="YYYY-MM-DD" value="' + esc(r0.date || '') + '"></div>' +
    '</div><small class="hint">The engineer on record is the owner of the facility. The person making this change is asked at the bottom.</small></fieldset>' +
    '<fieldset><legend>Network</legend><div class="grid2">' +
      '<div class="field"><label for="e_gcp">GCP &amp; Ring</label><select id="e_gcp">' + options(gcpOpts, r0.gcp) + '</select></div>' +
      '<div class="field"><label for="e_ven">Vendor</label><select id="e_ven">' + options(venOpts, r0.vendor) + '</select></div>' +
    '</div><div id="e_net"><div class="note">The IP addresses stay the same.</div></div></fieldset>';

  var regen = null, netErr = '', netSeq = 0, netBusy = false;
  function name() {
    var fac = $('#e_fac').value, num = $('#e_num').value;
    if (!std && !fac && !num) return { name: r0.name, err: '' };
    if (!fac || !num) return { name: r0.name, err: 'Choose a facility and type the well number.' };
    return { name: (fac + '-' + num).toUpperCase(), err: '' };
  }
  function plan() {
    var n = name(), eng = cleanPerson($('#e_eng').value), date = $('#e_date').value.trim(), g = $('#e_gcp').value, v = $('#e_ven').value, body = {}, err = n.err || netErr;
    if (n.name !== r0.name) body.name = n.name;
    if (eng !== cleanPerson(r0.engineer)) { body.engineer = eng; if (!err && checkPerson(eng)) err = 'Engineer on record: ' + esc(checkPerson(eng)); }
    if (date !== (r0.date || '')) { body.date = date; if (!err && !isIso(date)) err = 'The date must be a real date written as YYYY-MM-DD, for example ' + today() + '.'; }
    if (g !== r0.gcp || v !== r0.vendor) { body.gcp = g; body.vendor = v; if (regen) body.signature = regen.signature; if (!err && netBusy) err = 'Wait a moment: the new IPs are being calculated.'; }
    return { body: body, err: err, changed: Object.keys(body).length > 0 };
  }
  function refresh() {
    var n = name(), h = $('#e_nmh');
    h.className = 'hint ' + (n.err ? 'bad' : n.name !== r0.name ? 'ok' : '');
    h.innerHTML = n.err ? esc(n.err) : n.name !== r0.name ? 'New name: <b>' + esc(n.name) + '</b>' : 'Name stays <b>' + esc(r0.name) + '</b>';
    var p = plan();
    $('#dlgOk').disabled = !p.changed;
    $('#dlgOk').textContent = regen ? 'Save and regenerate IPs' : 'Save changes';
  }
  function network() {
    var g = $('#e_gcp').value, v = $('#e_ven').value, seq = ++netSeq;
    regen = null; netErr = '';
    if (g === r0.gcp && v === r0.vendor) { netBusy = false; $('#e_net').innerHTML = '<div class="note">The IP addresses stay the same.</div>'; return refresh(); }
    netBusy = true; $('#e_net').innerHTML = '<div class="note">Calculating the new IPs...</div>'; refresh();
    API.post('/records/' + r0.id + '/edit-preview', { gcp: g, vendor: v }).then(function (pv) {
      if (seq !== netSeq) return;
      netBusy = false; regen = pv;
      var fields = Object.keys(pv.old_ips).concat(Object.keys(pv.ips).filter(function (f) { return !(f in pv.old_ips); }));
      $('#e_net').innerHTML = '<div class="note warn"><b>New IPs will be generated</b> in ' + esc(g + ' / ' + v) + ' (host ' + pv.host + '). The old IPs are released when you save.</div>' +
        '<div style="max-height:190px;overflow:auto;margin-top:6px"><table class="diff"><thead><tr><th>Field</th><th>Now</th><th>After saving</th></tr></thead><tbody>' +
        fields.map(function (f) { var o = pv.old_ips[f] || '', n = pv.ips[f] || ''; return '<tr><td>' + esc(f) + '</td><td class="ip' + (o !== n ? ' old' : '') + '">' + esc(o || '-') + '</td><td class="ip' + (o !== n ? ' new' : '') + '">' + esc(n || '-') + '</td></tr>'; }).join('') +
        '</tbody></table></div>';
      refresh();
    }, function (e) {
      if (seq !== netSeq) return;
      netBusy = false; netErr = esc(e.message); $('#e_net').innerHTML = '<div class="note warn">' + netErr + '</div>'; refresh();
    });
  }
  var p = ask({ title: 'Modify ' + r0.name, body: body, ok: 'Save changes', wide: true, name: true, focus: '#e_num',
    check: function () { var x = plan(); return x.err || (x.changed ? '' : 'Nothing was changed.'); } });
  $('#e_num').addEventListener('input', function () { this.value = this.value.replace(/\D/g, ''); });
  ['#e_fac', '#e_num', '#e_eng', '#e_date'].forEach(function (s) { $(s).addEventListener('input', refresh); $(s).addEventListener('change', refresh); });
  $('#e_gcp').addEventListener('change', network); $('#e_ven').addEventListener('change', network);
  refresh();

  p.then(function (who) {
    if (!who) return;
    var x = plan(); x.body.actor = who.name; x.body.version = r0.version;
    run(API.patch('/records/' + r0.id, x.body), function (res) {
      return 'Saved changes to <b>' + esc(res.name) + '</b>' + (res.regenerated ? ' with new IPs (RTU IP-1 ' + esc(res.ips['RTU IP-1'] || '-') + '). The old IPs are free again.' : '.');
    });
  });
}
