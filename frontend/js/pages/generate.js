/* IP Generation: Generate = preview only (POST /generate/preview); Save re-checks on the server (POST /records). */
var pv = null, working = false, ranges = [];
var GR = [['RTU', ['RTU IP-1', 'RTU IP-2']], ['PLC', ['PLC IP-1', 'PLC IP-2']], ['RTU Internal', ['RTU Internal IP-1', 'RTU Internal IP-2']],
  ['HMI and Moxa', ['RTU-HMI IP', 'IES Moxa IP']], ['Shared: laptop, gateways, mask, VLAN', ['Engg. Laptop IP', 'Gateway-1', 'Gateway-2', 'Subnet Mask', 'RTU VLAN', 'PLC VLAN']]];

init('generate').then(function () {
  $('#fac').innerHTML = options(CFG.facilities); $('#gcp').innerHTML = options(CFG.gcps); $('#ven').innerHTML = options(CFG.vendors);
  var q = new URLSearchParams(location.search);
  if (CFG.gcps.indexOf(q.get('gcp')) >= 0) $('#gcp').value = q.get('gcp');
  if (CFG.vendors.indexOf(q.get('vendor')) >= 0) $('#ven').value = q.get('vendor');
  $('#eng').value = actor();
  $('#date').value = today();
  $('#f').addEventListener('input', changed);
  $('#f').addEventListener('change', changed);
  $('#f').addEventListener('submit', function (e) { e.preventDefault(); gen(); });
  clearPv();
  if (!CFG.facilities.length || !CFG.gcps.length || !CFG.vendors.length) msg('No facility, GCP &amp; Ring or vendor is enabled. Add them in <a href="settings.html">Settings</a> first.', 'warn');
  if (!q.get('gcp')) $('#num').focus();
  return loadRanges();
});

function loadRanges() { return API.get('/ranges').then(function (r) { ranges = r.ranges; drawRange(); }, function () {}); }
function body() { return { facility: $('#fac').value, well: $('#num').value.trim(), gcp: $('#gcp').value, vendor: $('#ven').value, engineer: cleanPerson($('#eng').value) }; }

/* ---------- live feedback while typing ---------- */
var checkName = debounce(function () {
  var n = $('#num').value, name = $('#fac').value + '-' + n;
  if (!n) return;
  API.get('/names/check?name=' + encodeURIComponent(name)).then(function (r) {
    if ($('#fac').value + '-' + $('#num').value !== name) return;      // the user kept typing
    var hint = $('#nmHint');
    hint.className = 'hint ' + (r.available ? 'ok' : 'bad');
    hint.innerHTML = r.available ? 'Full name: <b>' + esc(name) + '</b> &middot; available' : esc(name) + ': already exists' + (r.where === 'trash' ? ' (in the trash)' : '');
    $('#num').setAttribute('aria-invalid', r.available ? 'false' : 'true');
  }, function () {});
}, 250);

function changed() {
  var n = $('#num'); n.value = n.value.replace(/\D/g, '');
  var hint = $('#nmHint');
  hint.className = 'hint'; n.removeAttribute('aria-invalid');
  hint.innerHTML = 'Full name: <b>' + esc($('#fac').value + '-' + (n.value || '____')) + '</b>';
  checkName();
  drawRange();
  if (pv && !pv.saved) clearPv();
}
function drawRange() {
  var g = $('#gcp').value, v = $('#ven').value, r = ranges.filter(function (x) { return x.gcp === g && x.vendor === v; })[0];
  if (!r || r.state === 'none') { $('#rinfo').innerHTML = '<span class="mut">' + esc(g + ' / ' + v) + ': no active block</span>'; return; }
  var c = r.state === 'ok' ? '' : r.state;
  $('#rinfo').innerHTML = '<span>' + esc(g + ' / ' + v) + ': <b class="' + c + '">' + r.used + ' / ' + r.max + '</b> used</span>' +
    '<span class="' + c + '">' + (r.next ? 'next host ' + r.next : 'FULL') + '</span><div class="bar ' + c + '"><i style="width:' + Math.round(100 * r.used / r.max) + '%"></i></div>';
}
function clearPv() {
  pv = null; clearMsg();
  $('#pv').innerHTML = '<div class="pv-empty"><b>Preview</b><span>Fill in the form and press <b>Generate preview</b>.<br>All addresses for the new facility will appear here.</span></div>';
}

function show(r, note) {
  var ips = r.ips, notes = [];
  if (note) notes.push(note);
  if (r.skipped.length) notes.push('Host numbers ' + esc(r.skipped.join(', ')) + ' are busy (used or reserved), so host ' + r.host + ' was chosen.');
  if (r.warn) notes.push('<b class="warn">' + esc(r.gcp + ' / ' + r.vendor) + (r.saved ? ' is now ' : ' will be ') + r.used_after + ' of ' + r.capacity + ' used' + (r.full_after ? (r.saved ? ' (full)' : ' (full after this record)') : '') + '.</b>');
  $('#pv').innerHTML =
    '<div class="pvhead"><div><span class="nm">' + esc(r.name) + '</span>' + (r.saved ? '<span class="badge ok">Saved</span>' : '<span class="badge">Not saved yet</span>') +
    '<div class="mut" style="font-size:.82rem;margin-top:2px">' + esc(r.gcp + ' / ' + r.vendor) + ' &middot; host ' + r.host + ' of ' + r.capacity + ' &middot; ' + esc(r.engineer) + ' &middot; ' + esc(r.date) + '</div></div></div>' +
    (notes.length ? '<div class="note ' + (r.warn || note ? 'warn' : 'info') + '" style="margin:0 0 10px">' + notes.join('<br>') + '</div>' : '') +
    '<div class="groups">' + GR.filter(function (g) { return g[1].some(function (f) { return ips[f]; }); }).map(function (g, i) {
      return '<div class="gcard' + (i === 4 ? ' shared' : '') + '"><h3>' + g[0] + '</h3>' + g[1].filter(function (f) { return ips[f]; }).map(function (f) { return '<div><span>' + f + '</span><code>' + esc(ips[f]) + '</code></div>'; }).join('') + '</div>';
    }).join('') + '</div>' +
    '<div class="pvfoot">' + (r.saved
      ? '<button class="primary" type="button" id="btnNew">Create another facility</button><button type="button" id="btnCopy">Copy IPs</button><a class="btn ghost" href="worksheet.html">Open worksheet</a>'
      : '<button class="primary" type="button" id="btnSave">Save ' + esc(r.name) + '</button><button type="button" id="btnCopy">Copy IPs</button><small>Check the addresses, then save.</small>') + '</div>';
  $('#btnCopy').onclick = function () { copyIps(this); };
  if (r.saved) $('#btnNew').onclick = function () { $('#num').value = ''; pv = null; changed(); clearPv(); $('#num').focus(); };
  else $('#btnSave').onclick = save;
}

function copyIps(b) {
  if (!pv) return;
  var t = ['Facility Name\t' + pv.name, 'GCP & Ring\t' + pv.gcp, 'Vendor\t' + pv.vendor].concat(Object.keys(pv.ips).map(function (f) { return f + '\t' + pv.ips[f]; })).join('\n');
  var done = function () { b.textContent = 'Copied'; setTimeout(function () { b.textContent = 'Copy IPs'; }, 1500); };
  var old = function () { var a = document.createElement('textarea'); a.value = t; document.body.appendChild(a); a.select(); try { document.execCommand('copy'); } catch (e) {} a.remove(); done(); };
  if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(t).then(done, old); else old();
}
function focusFor(e) { return e.error === 'invalid_person' ? '#eng' : /name/.test(e.error || '') ? '#num' : null; }

function gen() {
  if (working) return;
  var b = body(), pe = checkPerson(b.engineer);
  if (!b.well) { clearPv(); msg('Type the well number (1 to 5 digits).'); return $('#num').focus(); }
  if (pe) { clearPv(); msg('TSU PAN Engineer: ' + esc(pe)); return $('#eng').focus(); }
  working = true; busy($('#btnGen'), true);
  API.post('/generate/preview', b).then(function (r) { clearMsg(); pv = r; show(r); }, function (e) { clearPv(); showErr(e); var f = focusFor(e); if (f) $(f).focus(); })
    .then(function () { working = false; busy($('#btnGen'), false); });
}

// Save sends the signature of the shown preview; the server recomputes and answers 409 with a new preview if anything changed
function save() {
  if (working || !pv || pv.saved) return;
  working = true; busy($('#btnSave'), true);
  var b = body(); b.signature = pv.signature;
  API.post('/records', b).then(function (rec) {
    setActor(rec.engineer); fillEngineerList();
    pv.saved = true; show(pv);
    msg('Saved <b>' + esc(rec.name) + '</b>. Its addresses are now reserved.', 1);
    loadRanges();
  }, function (e) {
    if (e.error === 'preview_changed' && e.preview) { pv = e.preview; show(pv, '<b>The addresses changed since your preview</b> (another change was saved meanwhile). Check the new preview and press Save again.'); loadRanges(); return; }
    clearPv(); showErr(e); loadRanges();
  }).then(function () { working = false; busy($('#btnSave'), false); });
}
