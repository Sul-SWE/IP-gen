/* Dashboard: numbers come ready from GET /api/dashboard. */
var VCOL = ['#1e7145', '#84bd00', '#2f7fb8', '#b9770e', '#7a5ea8'];
function vcol(vendors, v) { var i = vendors.indexOf(v); return i < 0 ? '#a9b8ae' : VCOL[i % VCOL.length]; }

init('index').then(function () {
  var admin = API.role === 'admin';
  $('#qa').innerHTML = (admin ? '<a class="btn primary" href="generate.html">+ New facility</a>' : '') +
    (admin || CFG.viewer_can_see_worksheet ? '<a class="btn" href="worksheet.html">Open worksheet</a>' : '');
  return API.get('/dashboard').then(draw, function (e) { showErr(e); $('#dash').innerHTML = ''; });
});

function draw(d) {
  var admin = API.role === 'admin', k = d.kpis, warnPct = Math.round(d.warn_at * 100);
  var pct = k.total ? Math.round(100 * k.used / k.total) : 0, att = k.attention;
  var kpis = [
    ['Active facilities', k.active, k.trash ? k.trash + ' in trash (IPs still reserved)' : 'Nothing in the trash', ''],
    ['Free host numbers', k.free, pct + '% used (' + k.used + ' of ' + k.total + ')', ''],
    ['Added in last 30 days', k.recent30, 'since ' + k.since, ''],
    ['Ranges needing attention', att.length, att.length ? att.slice(0, 2).join(', ') + (att.length > 2 ? ' +' + (att.length - 2) : '') : 'All ranges are below ' + warnPct + '%', k.any_full ? 'full' : att.length ? 'warn' : '']
  ];
  var out = '<div class="kpis">' + kpis.map(function (x) {
    return '<div class="kpi ' + x[3] + '"><small>' + x[0] + '</small><b data-n="' + x[1] + '">' + x[1] + '</b><small class="sub" title="' + esc(x[2]) + '">' + esc(x[2]) + '</small></div>';
  }).join('') + '</div>';

  /* address ranges: one row per GCP & Ring, one column per vendor */
  var gcps = [], byGcp = {};
  d.ranges.forEach(function (r) { if (!byGcp[r.gcp]) { byGcp[r.gcp] = { info: r, cells: {} }; gcps.push(r.gcp); } byGcp[r.gcp].cells[r.vendor] = r; });
  var vendors = d.vendors.filter(function (v) { return d.ranges.some(function (r) { return r.vendor === v; }); });
  var rows = gcps.map(function (g) {
    var info = byGcp[g].info;
    return '<tr><td class="rg"><b>' + esc(g) + '</b><small>' + esc(info.prefix) + '.x.x &middot; VLAN ' + esc(info.rtu_vlan) + ' / ' + esc(info.plc_vlan) + '</small></td>' + vendors.map(function (v) {
      var r = byGcp[g].cells[v];
      if (!r || r.state === 'none') return '<td data-l="' + esc(v) + '"><span class="mut">No active block</span></td>';
      var c = r.state === 'ok' ? '' : r.state, w = Math.round(100 * r.used / r.max);
      var nx = r.state === 'full'
        ? '<span class="full">Full' + (r.planned ? ': next block is ready, ask the admin to activate it' : ': no free host numbers') + '</span>'
        : 'Next: host ' + r.next + ' &rarr; RTU <code>' + esc(r.next_rtu) + '</code>';
      var extra = r.block_seq > 1 ? ' <small>block ' + r.block_seq + '</small>' : '';
      var inner = '<div class="bar ' + c + '"><i style="width:' + w + '%"></i></div><span class="nums ' + c + '">' + r.used + ' / ' + r.max + ' <small>used</small>' + extra + '</span><span class="nx">' + nx + '</span>';
      return '<td data-l="' + esc(v) + '">' + (admin && r.state !== 'full'
        ? '<a class="cell" href="generate.html?gcp=' + encodeURIComponent(g) + '&vendor=' + encodeURIComponent(v) + '" title="Create a facility in ' + esc(g + ' / ' + v) + '">' + inner + '</a>'
        : '<div class="cell">' + inner + '</div>') + '</td>';
    }).join('') + '</tr>';
  }).join('');
  var rangeP = '<section class="panel" aria-labelledby="hR"><div class="panel-h"><h2 id="hR">Address ranges</h2>' +
    '<div class="legend"><span><i style="background:var(--g)"></i>OK</span><span><i style="background:#d97706"></i>' + warnPct + '% or more</span><span><i style="background:var(--bad)"></i>Full</span></div></div>' +
    '<div style="overflow-x:auto"><table class="matrix"><thead><tr><th>GCP &amp; Ring</th>' + vendors.map(function (v) { return '<th>' + esc(v) + '</th>'; }).join('') + '</tr></thead><tbody>' +
    (rows || '<tr><td class="empty">No GCP &amp; Ring is configured yet.</td></tr>') + '</tbody></table></div>' +
    '<small style="margin-top:8px">Used = host numbers taken by active records and by records in the trash.' + (admin ? ' Click a range to create a facility in it.' : '') + '</small></section>';

  if (!k.active) {
    out += '<div class="dgrid">' + rangeP + '<section class="panel empty"><h2 style="justify-content:center">No records yet</h2>' +
      (admin ? '<p>Create the first facility, or import an existing sheet.</p><div class="row" style="justify-content:center"><a class="btn primary" href="generate.html">+ New facility</a><a class="btn" href="worksheet.html">Import Excel</a></div>'
             : '<p>The admin has not added any facility yet.</p>') + '</section></div>';
    $('#dash').innerHTML = out; $$('[data-n]').forEach(countUp); return;
  }

  /* facilities by area */
  var legendV = d.vendors.concat(d.vendor_totals.Other ? ['Other'] : []);
  var amax = Math.max.apply(null, d.areas.map(function (a) { return a.total; }).concat([1]));
  var fb = d.areas.map(function (a) {
    var segs = legendV.filter(function (v) { return a.by_vendor[v]; }).map(function (v) {
      return '<i style="width:' + (100 * a.by_vendor[v] / amax) + '%;background:' + vcol(d.vendors, v) + '" title="' + esc(v + ': ' + a.by_vendor[v]) + '"></i>';
    }).join('');
    return '<div class="fb"><b>' + esc(a.area) + '</b><div class="stack" role="img" aria-label="' + esc(a.area + ': ' + a.total + ' facilities') + '">' + segs + '</div><span class="n">' + a.total + '</span></div>';
  }).join('');
  var tots = legendV.filter(function (v) { return d.vendor_totals[v]; }).map(function (v) {
    return '<span><i style="display:inline-block;width:10px;height:10px;border-radius:3px;background:' + vcol(d.vendors, v) + '"></i> ' + esc(v) + ' <b>' + d.vendor_totals[v] + '</b> <small>' + Math.round(100 * d.vendor_totals[v] / k.active) + '%</small></span>';
  }).join('');
  var areaP = '<section class="panel" aria-labelledby="hA"><div class="panel-h"><h2 id="hA">Facilities by area</h2><small>Active records</small></div><div class="fbars">' + fb + '</div><div class="totals">' + tots + '</div></section>';

  /* per month */
  var mx = Math.max.apply(null, d.months.map(function (m) { return m.count; }).concat([1]));
  var monthP = '<section class="panel" aria-labelledby="hM"><div class="panel-h"><h2 id="hM">New facilities per month</h2><small>Last 6 months</small></div><div class="cols" role="img" aria-label="New facilities per month">' +
    d.months.map(function (m, i) { return '<div' + (i === 5 ? ' class="cur"' : '') + '><b>' + m.count + '</b><i style="height:' + Math.max(2, Math.round(80 * m.count / mx)) + '%"></i>' + esc(m.label) + '</div>'; }).join('') + '</div></section>';

  /* recent activity */
  var actP = '<section class="panel" aria-labelledby="hL"><div class="panel-h"><h2 id="hL">Recent activity</h2>' + (admin ? '<a class="more" href="management.html#log">Open the full change log &rarr;</a>' : '') + '</div><ul class="acts">' +
    (d.recent.map(function (l) { return '<li><span class="t">' + esc(l.at) + '</span><span class="w">' + esc(l.who) + '</span>' + chip(l.action) + '<code title="' + esc(l.details) + '">' + esc(l.name) + '</code></li>'; }).join('') || '<li>No activity yet.</li>') + '</ul></section>';

  out += '<div class="dgrid">' + rangeP + areaP + '</div><div class="dgrid b">' + monthP + actP + '</div>';
  $('#dash').innerHTML = out;
  $$('[data-n]').forEach(countUp);
}
