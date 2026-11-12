/* Page frame for every page: who is using the tool, header, dialogs, acting engineer name. */
var CFG = null;
var PAGES = [
  { id: 'index', title: 'Dashboard', admin: false },
  { id: 'generate', title: 'IP Generation', admin: true },
  { id: 'management', title: 'IP Management', admin: true },
  { id: 'worksheet', title: 'Worksheet', admin: false },
  { id: 'settings', title: 'Settings', admin: true }
];

/* ---------- acting engineer: typed once, remembered for this browser session ---------- */
function actor() { try { return sessionStorage.getItem('actor') || ''; } catch (e) { return ''; } }
function setActor(n) { try { sessionStorage.setItem('actor', n); } catch (e) {} drawActor(); }
function drawActor() {
  var b = $('#actorBtn'); if (!b) return;
  var a = actor();
  b.innerHTML = a ? '<span class="dot"></span>' + esc(a) : 'Set your name';
  b.title = a ? 'You are recorded in the change log as ' + a + '. Click to change.' : 'Type your name once; it is recorded in the change log.';
}
function fillEngineerList() {
  if (API.role !== 'admin') return Promise.resolve();
  return API.get('/engineers/suggest').then(function (r) {
    var names = r.names.slice(); if (actor() && names.indexOf(actor()) < 0) names.push(actor());
    $('#engList').innerHTML = names.map(function (n) { return '<option value="' + esc(n) + '">'; }).join('');
  }, function () {});
}

/* ---------- dialog ----------
   ask({title, body (html), ok, danger, wide, name:true, check:fn}) -> Promise of {name} or null.
   name:true asks for the acting engineer (pre-filled). check() may return an error (html) to keep the dialog open. */
function ask(o) {
  var d = $('#dlg');
  d.className = o.wide ? 'wide' : '';
  d.innerHTML = '<form method="dialog" novalidate><h2 id="dlgT">' + esc(o.title) + '</h2><div class="dlg-body">' + (o.body || '') + '</div><div id="dlgMsg" class="msg"></div>' +
    (o.name ? '<div class="field"><label for="dlgName">Your name <small>(recorded in the change log)</small></label><input id="dlgName" list="engList" autocomplete="off" maxlength="40" value="' + esc(actor()) + '"><small class="err" id="dlgErr"></small></div>' : '') +
    '<div class="dlg-actions"><button type="button" id="dlgNo">' + esc(o.cancel || 'Cancel') + '</button><button type="submit" class="' + (o.danger ? 'danger solid' : 'primary') + '" id="dlgOk">' + esc(o.ok || 'OK') + '</button></div></form>';
  fillEngineerList();
  return new Promise(function (done) {
    var finish = function (v) { d.close(); done(v); };
    $('#dlgNo').onclick = function () { finish(null); };
    d.oncancel = function (e) { e.preventDefault(); finish(null); };
    $('form', d).onsubmit = function (e) {
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
    var first = o.focus ? $(o.focus) : o.name && !actor() ? $('#dlgName') : $('#dlgOk');
    setTimeout(function () { if (first) first.focus(); }, 30);
  });
}
function askActor() {
  return ask({ title: 'Who is working?', ok: 'Save name', name: true,
    body: '<p>The admin account is shared, so type your own name. It is saved with every change you make in this browser session.</p>' });
}

/* ---------- page frame ---------- */
function init(page) {
  var def = PAGES.filter(function (p) { return p.id === page; })[0] || { admin: false };
  document.body.insertAdjacentHTML('afterbegin', '<a class="skip" href="#main">Skip to content</a><header><a class="brand" href="index.html"><span class="logo" aria-hidden="true">IP</span>IP Generator</a><nav aria-label="Main" id="nav"></nav><span id="who"></span></header>');
  $('main').id = 'main';
  document.body.insertAdjacentHTML('beforeend', '<footer>Dummy test rules. Always verify a real IP in the field (ping / arp) before using it.</footer><dialog id="dlg" aria-labelledby="dlgT"></dialog><datalist id="engList"></datalist>');

  return Promise.all([API.get('/auth/me'), API.get('/config')]).then(function (r) {
    API.me = r[0]; API.role = r[0].role; API.csrf = r[0].csrf || ''; CFG = r[1];
    if (def.admin && API.role !== 'admin') { API.role = 'admin'; API.signedOut('login_required'); return new Promise(function () {}); }
    var admin = API.role === 'admin';
    $('#nav').innerHTML = PAGES.filter(function (p) { return admin ? true : !p.admin && (p.id !== 'worksheet' || CFG.viewer_can_see_worksheet); })
      .map(function (p) { return '<a href="' + p.id + '.html"' + (p.id === page ? ' class="on" aria-current="page"' : '') + '>' + p.title + '</a>'; }).join('');
    $('#who').innerHTML = admin
      ? '<button type="button" class="actor" id="actorBtn"></button><button type="button" class="actor out" id="outBtn" title="Sign out so another engineer can sign in">Sign out</button>'
      : '<span class="role">Viewer (read only)</span><a class="actor" href="login.html">Admin sign in</a>';
    document.body.classList.add(admin ? 'is-admin' : 'is-viewer');
    if (admin) {
      drawActor();
      $('#actorBtn').onclick = function () { askActor(); };
      $('#outBtn').onclick = function () { API.post('/auth/logout').then(function () { location.href = 'index.html'; }, function () { location.href = 'index.html'; }); };
      // keeps the session marked as active, and notices when another admin took over or the session expired
      setInterval(function () { API.get('/auth/me').then(function (m) { if (m.role !== 'admin') API.signedOut('expired'); }, function () {}); }, 60000);
      fillEngineerList();
    }
    smoothLinks();
    return CFG;
  }, function (e) {
    $('main').insertAdjacentHTML('afterbegin', '<div class="msg bad" role="alert">' + errHtml(e) + '</div>');
    return new Promise(function () {});
  });
}
function smoothLinks() {
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a[href]');
    if (!a || e.defaultPrevented || e.button || e.metaKey || e.ctrlKey || e.shiftKey || a.target || a.hasAttribute('download') || !/\.html(\?|#|$)/.test(a.getAttribute('href')) || REDUCED) return;
    e.preventDefault(); document.body.classList.add('leaving');
    setTimeout(function () { location.href = a.href; }, 120);
  });
  window.addEventListener('pageshow', function () { document.body.classList.remove('leaving'); });
}
