/* Worksheet: read-only table for everyone; export, import (preview then confirm) and undo for the admin. */
var rows = [], page = 1, pages = 1, total = 0, counts = null, loadSeq = 0, lastImport = null;

init('worksheet').then(function () {
  var admin = API.role === 'admin';
  $('#sub').textContent = admin ? 'All records in one read-only table. Export is the backup; import only adds new rows.' : 'All records in one read-only table.';
  $('#q').oninput = debounce(function () { load(true); }, 250);
  $('#sd').onchange = function () { load(true); };
  if (admin) {
    $('#btnExp').onclick = exp;
    $('#btnImp').onkeydown = function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); $('#impf').click(); } };
    $('#impf').onchange = function () { var f = this.files[0]; this.value = ''; if (f) imp(f); };
    $('#btnUndo').onclick = undo;
    loadLast();
  }
  return load(true);
});

/* ---------- table ---------- */
function load(reset) {
  if (reset) { page = 1; rows = []; }
  var seq = ++loadSeq;
  return API.get('/records?status=' + ($('#sd').checked ? 'all' : 'active') + '&q=' + encodeURIComponent($('#q').value.trim()) + '&page=' + page + '&size=200').then(function (r) {
    if (seq !== loadSeq) return;
    rows = reset ? r.items : rows.concat(r.items);
    pages = r.pages; total = r.total; counts = r.counts; draw();
  }, function (e) { if (seq === loadSeq) showErr(e); });
}
function draw() {
  var cols = CFG.columns, q = $('#q').value.trim();
  $('#count').textContent = rows.length + ' of ' + total + ' row(s) shown · ' + counts.active + ' active' + (counts.trash ? ', ' + counts.trash + ' in trash' : '');
  var cell = function (r, c) { return c === 'Facility Name' ? r.name : c === 'GCP & Ring' ? r.gcp : c === 'Vendor' ? r.vendor : c === 'Date' ? r.date : c === 'TSU PAN Engineer' ? r.engineer : (r.ips[c] || ''); };
  $('#t').innerHTML = '<thead><tr><th class="rn" aria-label="Row"></th>' + cols.map(function (c, i) { return '<th' + (i === 0 ? ' class="nm"' : '') + '>' + esc(c) + '</th>'; }).join('') + '</tr></thead><tbody>' +
    (rows.map(function (r, i) {
      return '<tr' + (r.status === 'trash' ? ' class="del" title="In the trash: name and IPs are still reserved"' : '') + '><td class="rn">' + (i + 1) + '</td>' +
        cols.map(function (c, j) { return '<td' + (j === 0 ? ' class="nm"' : CFG.ip_columns.indexOf(c) >= 0 ? ' class="ip"' : '') + '>' + esc(cell(r, c)) + '</td>'; }).join('') + '</tr>';
    }).join('') || '<tr><td class="rn"></td><td colspan="' + cols.length + '" class="empty" style="text-align:left">' + (q ? 'No rows match the filter.' : 'No records yet.') + '</td></tr>') + '</tbody>';
  $('#more').innerHTML = page < pages ? '<button class="sm" id="moreBtn">Show more rows</button>' : '';
  if (page < pages) $('#moreBtn').onclick = function () { page++; load(false); };
}

/* ---------- export ---------- */
function exp() {
  busy($('#btnExp'), true);
  API.download('/export').then(function (r) { msg('Exported ' + r.count + ' active record(s) to <b>' + esc(r.name) + '</b>. Keep it as a backup.', 1); }, showErr)
    .then(function () { busy($('#btnExp'), false); });
}

/* ---------- import: step 1 preview (nothing is written), step 2 confirm ---------- */
function reasons(a) { return a.length ? '<ul>' + a.map(function (e) { return '<li>' + esc(e) + '</li>'; }).join('') + '</ul>' : ''; }
function imp(f) {
  if (!/\.xlsx$/i.test(f.name || '')) return msg('Please choose an Excel file (.xlsx). Older .xls files: open in Excel and use Save As .xlsx. Nothing was imported.');
  if (f.size > 5 * 1024 * 1024) return msg('This file is larger than 5 MB. Nothing was imported.');
  msg('Checking <b>' + esc(f.name) + '</b>...', 'info');
  API.upload('/import/preview', f).then(function (p) {
    clearMsg();
    var body = '<p class="mut" style="font-size:.84rem"><b>' + esc(p.filename) + '</b> &middot; sheet "' + esc(p.sheet) + '" &middot; ' + p.rows + ' data row(s) &middot; ' + p.columns + ' known column(s). Nothing has been saved yet.</p>' +
      '<div class="sum"><div class="a"><small>Will be added</small><b>' + p.will_add + '</b></div><div class="s"><small>Will be skipped</small><b>' + p.will_skip + '</b></div><div class="w"><small>Added with notes</small><b>' + p.with_notes + '</b></div></div>' +
      (p.issues.length ? '<div class="imp"><div class="tw"><table><thead><tr><th>Row</th><th>Facility</th><th>Result</th><th>Reason</th></tr></thead><tbody>' +
        p.issues.map(function (r) { return '<tr><td>' + r.line + '</td><td>' + esc(r.name) + '</td><td class="st">' + (r.add ? '<span class="chip w">Add, note</span>' : '<span class="chip r">Skip</span>') + '</td><td>' + reasons(r.reasons) + '</td></tr>'; }).join('') +
        '</tbody></table></div>' + (p.issues_total > p.issues.length ? '<small>Showing the first ' + p.issues.length + ' of ' + p.issues_total + ' rows with remarks.</small>' : '') + '</div>'
        : '<div class="note info">Every row passed all checks.</div>') +
      '<div class="note">Import only <b>adds</b> new rows. Existing records are never changed. Rows that repeat a name or an IP of any record (active or in the trash), or of an earlier row in this file, are skipped.</div>';
    ask({ title: 'Import preview', body: body, wide: true, name: true, ok: p.will_add ? 'Import ' + p.will_add + ' row(s)' : 'Nothing to import',
      check: function () { return p.will_add ? '' : 'No row can be imported. Fix the file and try again.'; } })
    .then(function (who) {
      if (!who) return msg('Import cancelled. Nothing was imported.', 'info');
      API.post('/import/confirm', { token: p.token, actor: who.name }).then(function (r) {
        msg('Imported <b>' + r.imported + '</b> row(s) from ' + esc(r.filename) + '. Skipped ' + r.skipped + '.' +
          (r.skipped_rows.length ? '<ul>' + r.skipped_rows.map(function (b) { return '<li>Row ' + b.line + ' (' + esc(b.name) + '): ' + esc(b.reasons.join('; ')) + '</li>'; }).join('') + (r.skipped > r.skipped_rows.length ? '<li>and ' + (r.skipped - r.skipped_rows.length) + ' more rows</li>' : '') + '</ul>' : '') +
          ' You can undo this import while none of its rows has been changed.', r.skipped ? 'warn' : 1);
        load(true); loadLast(); fillEngineerList();
      }, function (e) { showErr(e); load(true); });
    });
  }, showErr);
}

/* ---------- undo last import ---------- */
function loadLast() {
  return API.get('/import/last').then(function (r) {
    lastImport = r.last;
    $('#btnUndo').disabled = !lastImport;
    $('#btnUndo').title = lastImport ? 'Remove the ' + lastImport.count + ' row(s) added from ' + lastImport.file + ' on ' + lastImport.at + (lastImport.can_undo ? '' : ' (not possible: ' + lastImport.why + ')') : 'No import to undo';
  }, function () {});
}
function undo() {
  loadLast().then(function () {
    var li = lastImport; if (!li) return;
    if (!li.can_undo) return msg('The last import cannot be undone: ' + esc(li.why) + '. Undo only works while every imported row is unchanged.', 'warn');
    ask({ title: 'Undo the last import?', danger: true, ok: 'Remove ' + li.count + ' row(s)', name: true,
      body: '<p>This removes exactly the <b>' + li.count + '</b> row(s) added from <b>' + esc(li.file) + '</b> on ' + esc(li.at) + ' by ' + esc(li.who) + '. Their names and IPs become free. No other record is touched.</p>' })
    .then(function (who) {
      if (!who) return;
      API.post('/import/undo-last', { actor: who.name, batch: li.batch }).then(function (r) { msg('Removed the ' + r.removed + ' row(s) of the last import.', 1); load(true); loadLast(); },
        function (e) { showErr(e); load(true); loadLast(); });
    });
  });
}
