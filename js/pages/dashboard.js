/* Dashboard: numbers come ready from GET /api/dashboard; charts are drawn with Chart.js (lib/chart.umd.min.js). */
var PALETTE = ['#1e7145', '#84bd00', '#2f7fb8', '#d08a1e', '#7a5ea8'], OTHER = '#b9c6be';
var charts = [];
function vcol(vendors, v) { var i = vendors.indexOf(v); return i < 0 ? OTHER : PALETTE[i % PALETTE.length]; }

init('index').then(function () {
  var admin = API.role === 'admin';
  $('#qa').innerHTML = (admin || CFG.viewer_can_see_worksheet ? '<a class="btn" href="worksheet.html">Open worksheet</a>' : '') +
    (admin ? '<a class="btn primary" href="generate.html">+ New facility</a>' : '');
  return API.get('/dashboard').then(draw, function (e) { showErr(e); $('#dash').innerHTML = ''; });
});

function chartDefaults() {
  if (!window.Chart) return false;
  Chart.defaults.font.family = '"Segoe UI", system-ui, -apple-system, Arial, sans-serif';
  Chart.defaults.font.size = window.matchMedia && matchMedia('(min-width: 1000px)').matches ? 11 : 12;   // matches the 90% page size on laptops
  Chart.defaults.color = '#6b7a71';
  Chart.defaults.borderColor = '#edf1ee';
  Chart.defaults.plugins.legend.display = false;
  Chart.defaults.plugins.tooltip.backgroundColor = '#1f2d25';
  Chart.defaults.plugins.tooltip.padding = 10;
  Chart.defaults.plugins.tooltip.cornerRadius = 8;
  Chart.defaults.maintainAspectRatio = false;
  if (REDUCED) Chart.defaults.animation = false;
  return true;
}

// writes the total in the middle of the ring chart
var centerText = {
  id: 'centerText',
  afterDraw: function (c) {
    var t = c.options.plugins.centerText; if (!t) return;
    var a = c.chartArea, x = (a.left + a.right) / 2, y = (a.top + a.bottom) / 2, ctx = c.ctx;
    ctx.save(); ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillStyle = '#124a2d'; ctx.font = '700 26px "Segoe UI", system-ui, sans-serif'; ctx.fillText(t.value, x, y - 8);
    ctx.fillStyle = '#6b7a71'; ctx.font = '12px "Segoe UI", system-ui, sans-serif'; ctx.fillText(t.label, x, y + 14);
    ctx.restore();
  }
};

function draw(d) {
  charts.forEach(function (c) { c.destroy(); }); charts = [];
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

  /* ----- address ranges: one row per GCP & Ring, one column per vendor ----- */
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
        : '<span title="Host number and RTU IP-1 the next facility will get">Next #' + r.next + ' &rarr; <code>' + esc(r.next_rtu) + '</code></span>';
      var extra = r.block_seq > 1 ? ' <small>&middot; block ' + r.block_seq + '</small>' : '';
      var inner = '<div class="bar ' + c + '"><i style="width:' + w + '%"></i></div><span class="nums ' + c + '">' + r.used + ' / ' + r.max + extra + '</span><span class="nx">' + nx + '</span>';
      return '<td data-l="' + esc(v) + '">' + (admin && r.state !== 'full'
        ? '<a class="cell" href="generate.html?gcp=' + encodeURIComponent(g) + '&vendor=' + encodeURIComponent(v) + '" title="Create a facility in ' + esc(g + ' / ' + v) + '">' + inner + '</a>'
        : '<div class="cell">' + inner + '</div>') + '</td>';
    }).join('') + '</tr>';
  }).join('');
  var rangeP = '<section class="panel" aria-labelledby="hR"><div class="panel-h"><h2 id="hR">Address ranges</h2>' +
    '<div class="legend"><span><i style="background:var(--g2)"></i>OK</span><span><i style="background:#e08a1e"></i>' + warnPct + '% or more</span><span><i style="background:var(--bad)"></i>Full</span></div></div>' +
    '<div style="overflow-x:auto"><table class="matrix"><thead><tr><th>GCP &amp; Ring</th>' + vendors.map(function (v) { return '<th>' + esc(v) + '</th>'; }).join('') + '</tr></thead><tbody>' +
    (rows || '<tr><td class="empty">No GCP &amp; Ring is configured yet.</td></tr>') + '</tbody></table></div>' +
    '<small style="margin-top:10px">Used host numbers include records in the trash.' + (admin ? ' Click a range to create a facility in it.' : '') + '</small></section>';

  if (!k.active) {
    out += '<div class="dgrid">' + rangeP + '<section class="panel empty"><h2 style="justify-content:center">No records yet</h2>' +
      (admin ? '<p>Create the first facility, or import an existing sheet.</p><div class="row" style="justify-content:center"><a class="btn primary" href="generate.html">+ New facility</a><a class="btn" href="worksheet.html">Import Excel</a></div>'
             : '<p>The admin has not added any facility yet.</p>') + '</section></div>';
    $('#dash').innerHTML = out; $$('[data-n]').forEach(countUp); return;
  }

  var legendV = d.vendors.concat(d.vendor_totals.Other ? ['Other'] : []).filter(function (v) { return d.vendor_totals[v]; });
  var vendorP = '<section class="panel" aria-labelledby="hV"><div class="panel-h"><h2 id="hV">Facilities by vendor</h2><small>Active records</small></div>' +
    '<div class="chart donut"><canvas id="cVendor" role="img" aria-label="Facilities by vendor">' + legendV.map(function (v) { return esc(v) + ': ' + d.vendor_totals[v]; }).join(', ') + '</canvas></div>' +
    '<div class="totals">' + legendV.map(function (v) {
      return '<span><i style="background:' + vcol(d.vendors, v) + '"></i>' + esc(v) + ' <b>' + d.vendor_totals[v] + '</b> <small>' + Math.round(100 * d.vendor_totals[v] / k.active) + '%</small></span>';
    }).join('') + '</div></section>';
  var monthP = '<section class="panel" aria-labelledby="hM"><div class="panel-h"><h2 id="hM">New facilities per month</h2><small>Last 6 months</small></div>' +
    '<div class="chart"><canvas id="cMonth" role="img" aria-label="New facilities per month">' + d.months.map(function (m) { return esc(m.label) + ': ' + m.count; }).join(', ') + '</canvas></div></section>';
  var areaP = '<section class="panel" aria-labelledby="hA"><div class="panel-h"><h2 id="hA">Facilities by area</h2><small>Split by vendor</small></div>' +
    '<div class="chart"><canvas id="cArea" role="img" aria-label="Facilities by area">' + d.areas.map(function (a) { return esc(a.area) + ': ' + a.total; }).join(', ') + '</canvas></div></section>';
  var actP = '<section class="panel" aria-labelledby="hL"><div class="panel-h"><h2 id="hL">Recent activity</h2>' + (admin ? '<a class="more" href="management.html#log">Full log &rarr;</a>' : '') + '</div><ul class="acts">' +
    (d.recent.slice(0, 4).map(function (l) { return '<li><span class="w">' + esc(l.who) + '</span>' + chip(l.action) + '<span class="t"><code title="' + esc(l.details) + '">' + esc(l.name) + '</code><span>' + esc(l.at) + '</span></span></li>'; }).join('') || '<li>No activity yet.</li>') + '</ul></section>';

  out += '<div class="dgrid">' + rangeP + vendorP + '</div><div class="dgrid three">' + monthP + areaP + actP + '</div>';
  $('#dash').innerHTML = out;
  $$('[data-n]').forEach(countUp);
  if (!chartDefaults()) return;   // the numbers above are still shown if Chart.js could not load

  charts.push(new Chart($('#cVendor'), {
    type: 'doughnut',
    data: { labels: legendV, datasets: [{ data: legendV.map(function (v) { return d.vendor_totals[v]; }), backgroundColor: legendV.map(function (v) { return vcol(d.vendors, v); }), borderColor: '#fff', borderWidth: 3, hoverOffset: 4 }] },
    options: { cutout: '68%', plugins: { centerText: { value: String(k.active), label: 'facilities' } } },
    plugins: [centerText]
  }));
  var last = d.months.length - 1;
  charts.push(new Chart($('#cMonth'), {
    type: 'bar',
    data: { labels: d.months.map(function (m) { return m.label; }), datasets: [{ label: 'New facilities', data: d.months.map(function (m) { return m.count; }),
      backgroundColor: d.months.map(function (_, i) { return i === last ? '#84bd00' : '#2e8b57'; }), borderRadius: 6, maxBarThickness: 34 }] },
    options: { scales: { x: { grid: { display: false } }, y: { beginAtZero: true, ticks: { precision: 0 } } } }
  }));
  charts.push(new Chart($('#cArea'), {
    type: 'bar',
    data: { labels: d.areas.map(function (a) { return a.area; }),
      datasets: legendV.map(function (v) { return { label: v, data: d.areas.map(function (a) { return a.by_vendor[v] || 0; }), backgroundColor: vcol(d.vendors, v), borderRadius: 4, maxBarThickness: 22 }; }) },
    options: { indexAxis: 'y', plugins: { legend: { display: true, position: 'bottom', labels: { boxWidth: 10, boxHeight: 10, useBorderRadius: true, borderRadius: 3 } } },
      scales: { x: { stacked: true, beginAtZero: true, ticks: { precision: 0 } }, y: { stacked: true, grid: { display: false } } } }
  }));
}
