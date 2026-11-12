/* Shared page helpers: header, banners, dialogs, acting engineer, dates. */
var $ = function (s, el) { return (el || document).querySelector(s); };
var $$ = function (s, el) { return Array.prototype.slice.call((el || document).querySelectorAll(s)); };
var S = null, esc = h;
var REDUCED = !!(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches);

/* ---------- dates: always English digits ---------- */
function p2(n) { return String(n).padStart(2, '0'); }
function isoOf(d) { return d.getFullYear() + '-' + p2(d.getMonth() + 1) + '-' + p2(d.getDate()); }
function today() { return isoOf(new Date()); }
function stamp() { var d = new Date(); return today() + ' ' + p2(d.getHours()) + ':' + p2(d.getMinutes()); }
var isIso = isIsoDate;

/* ---------- banners (text must already be escaped) ---------- */
function msg(t, kind, id) {
  var m = $(id || '#msg'); if (!m) return;
  m.className = 'msg ' + (kind === 1 || kind === 'ok' ? 'ok' : kind === 'warn' ? 'warn' : kind === 'info' ? 'info' : 'bad');
  m.innerHTML = t;
  m.setAttribute('role', m.className.indexOf('bad') > 0 ? 'alert' : 'status');
}
function clearMsg(id) { var m = $(id || '#msg'); if (m) { m.className = 'msg'; m.innerHTML = ''; } }

function sel(id, arr, ph) {
  $(id).innerHTML = (ph ? '<option value="">' + esc(ph) + '</option>' : '') +
    arr.map(function (x) { return '<option>' + esc(x) + '</option>'; }).join('');
}

/* ---------- acting engineer: typed once, remembered for this browser session ---------- */
function actor() { try { return sessionStorage.getItem('actor') || ''; } catch (e) { return ''; } }
function setActor(n) { try { sessionStorage.setItem('actor', n); } catch (e) {} drawActor(); }
function drawActor() {
  var b = $('#actorBtn'); if (!b) return;
  var a = actor();
  b.innerHTML = a ? '<span class="dot"></span>' + esc(a) : 'Set your name';
  b.title = a ? 'You are recorded in the change log as ' + a + '. Click to change.' : 'Type your name once; it is recorded in the change log.';
}
// names already used in records and in the log, for autocomplete
function engineerNames() {
  var m = {};
  if (S) {
    S.records.forEach(function (r) { if (r.engineer && !checkPerson(r.engineer)) m[cleanPerson(r.engineer)] = 1; });
    S.log.forEach(function (l) { if (l.who && !checkPerson(l.who)) m[cleanPerson(l.who)] = 1; });
  }
  if (actor()) m[actor()] = 1;
  return Object.keys(m).sort(function (a, b) { return a.localeCompare(b); });
}
function fillEngineerList() {
  var d = $('#engList'); if (d) d.innerHTML = engineerNames().map(function (n) { return '<option value="' + esc(n) + '">'; }).join('');
}

/* ---------- dialog ----------
   ask({title, body (html), ok, danger, wide, name:true, check:fn}) -> Promise of {name} or null.
   With name:true the dialog asks for the acting engineer (pre-filled) and validates it.
   check() may return an error (html) to keep the dialog open. */
function ask(o) {
  var d = $('#dlg');
  d.className = o.wide ? 'wide' : '';
  d.innerHTML = '<form method="dialog" novalidate><h2 id="dlgT">' + esc(o.title) + '</h2><div class="dlg-body">' + (o.body || '') + '</div><div id="dlgMsg" class="msg"></div>' +
    (o.name ? '<div class="field"><label for="dlgName">Your name <small>(recorded in the change log)</small></label><input id="dlgName" list="engList" autocomplete="off" maxlength="40" value="' + esc(actor()) + '"><small class="err" id="dlgErr"></small></div>' : '') +
    '<div class="dlg-actions"><button type="button" value="cancel" id="dlgNo">Cancel</button><button type="submit" value="ok" class="' + (o.danger ? 'danger solid' : 'primary') + '" id="dlgOk">' + esc(o.ok || 'OK') + '</button></div></form>';
  fillEngineerList();
  return new Promise(function (done) {
    var f = $('form', d), finish = function (v) { d.close(); done(v); };
    $('#dlgNo').onclick = function () { finish(null); };
    d.oncancel = function (e) { e.preventDefault(); finish(null); };
    f.onsubmit = function (e) {
      e.preventDefault();
      var c = o.check ? o.check() : '';
      if (c) { msg(c, 'bad', '#dlgMsg'); return; }
      clearMsg('#dlgMsg');
      if (o.name) {
        var n = cleanPerson($('#dlgName').value), er = checkPerson(n);
        if (er) { $('#dlgErr').textContent = er; $('#dlgName').setAttribute('aria-invalid', 'true'); $('#dlgName').focus(); return; }
        setActor(n);
        return finish({ name: n });
      }
      finish({});
    };
    d.showModal();
    var first = o.name && !actor() ? $('#dlgName') : $('#dlgOk');
    setTimeout(function () { first.focus(); }, 30);
  });
}
function askActor() {
  return ask({ title: 'Who is working?', body: '<p>The tool uses one shared account, so type your own name. It is saved with every change you make in this browser session.</p>', ok: 'Save name', name: true });
}

/* ---------- change log ---------- */
function logTo(st, who, act, name, det) { st.log.unshift({ t: stamp(), who: who, act: act, name: name, det: det || '' }); }
function chip(a) {
  var c = /^(Created|Restored|Imported)/.test(a) ? 'g' : /^(Deleted|Import undone)/.test(a) ? 'r' : /^Modified/.test(a) ? 'b' : '';
  return '<span class="chip ' + c + '">' + esc(a) + '</span>';
}

/* ---------- count-up numbers ---------- */
function countUp(el) {
  var n = +el.dataset.n, sfx = el.dataset.s || '';
  if (n < 2 || REDUCED) return;
  var t0 = null;
  (function f(t) { t0 = t0 || t; var p = Math.min(1, (t - t0) / 500); el.textContent = Math.round(n * p) + sfx; if (p < 1) requestAnimationFrame(f); })(performance.now());
}

/* ---------- page frame ---------- */
var PAGES = [['index', 'Dashboard'], ['generate', 'IP Generation'], ['management', 'IP Management'], ['worksheet', 'Worksheet']];
function init(page) {
  document.body.insertAdjacentHTML('afterbegin',
    '<a class="skip" href="#main">Skip to content</a><header><a class="brand" href="index.html"><span class="logo" aria-hidden="true">IP</span>IP Generator</a><nav aria-label="Main">' +
    PAGES.map(function (a) { return '<a href="' + a[0] + '.html"' + (a[0] === page ? ' class="on" aria-current="page"' : '') + '>' + a[1] + '</a>'; }).join('') +
    '</nav><button type="button" class="actor" id="actorBtn"></button></header>');
  $('main').id = 'main';
  document.body.insertAdjacentHTML('beforeend', '<footer>Test version with dummy rules. Always verify a real IP in the field (ping / arp) before using it.</footer><dialog id="dlg" aria-labelledby="dlgT"></dialog><datalist id="engList"></datalist>');
  drawActor();
  $('#actorBtn').onclick = function () { askActor(); };
  // smooth page change
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a[href]');
    if (!a || e.defaultPrevented || e.button || e.metaKey || e.ctrlKey || e.shiftKey || a.target || !/\.html(\?|#|$)/.test(a.getAttribute('href')) || REDUCED) return;
    e.preventDefault(); document.body.classList.add('leaving');
    setTimeout(function () { location.href = a.href; }, 120);
  });
  window.addEventListener('pageshow', function () { document.body.classList.remove('leaving'); });
  return DB.load().then(function (s) { S = s; fillEngineerList(); return s; }, function () {
    msg('Browser storage is not available. Do not use a private window. Open the tool in a normal Edge or Chrome window.');
    return new Promise(function () {});
  });
}
