/* Small helpers shared by every page. No data access here. */
var $ = function (s, el) { return (el || document).querySelector(s); };
var $$ = function (s, el) { return Array.prototype.slice.call((el || document).querySelectorAll(s)); };
var REDUCED = !!(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches);

// every text that comes from the server or the user goes through esc() before it is put into HTML
function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

/* dates: always English digits */
function p2(n) { return String(n).padStart(2, '0'); }
function today() { var d = new Date(); return d.getFullYear() + '-' + p2(d.getMonth() + 1) + '-' + p2(d.getDate()); }
function isIso(s) {
  var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s); if (!m) return false;
  var d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  return d.getUTCFullYear() === +m[1] && d.getUTCMonth() === +m[2] - 1 && d.getUTCDate() === +m[3];
}

/* person names typed by the engineer (the server checks again) */
function cleanPerson(s) { return String(s == null ? '' : s).trim().replace(/\s+/g, ' '); }
function checkPerson(s) {
  s = cleanPerson(s);
  if (s.length < 2 || s.length > 40) return 'Type your name (2 to 40 characters).';
  if (!/^[\p{L}][\p{L}\p{M} .'-]*$/u.test(s)) return 'A name may only contain letters, spaces, dots, dashes and apostrophes.';
  return '';
}

/* banners */
function msg(html, kind, id) {
  var m = $(id || '#msg'); if (!m) return;
  m.className = 'msg ' + (kind === 1 || kind === 'ok' ? 'ok' : kind === 'warn' ? 'warn' : kind === 'info' ? 'info' : 'bad');
  m.innerHTML = html;
  m.setAttribute('role', /bad/.test(m.className) ? 'alert' : 'status');
}
function clearMsg(id) { var m = $(id || '#msg'); if (m) { m.className = 'msg'; m.innerHTML = ''; } }
// show an error object from the API: message plus the list of details
function errHtml(e) {
  var d = (e && e.details) || [];
  return esc((e && e.message) || 'Something went wrong. Please try again.') +
    (d.length ? '<ul>' + d.slice(0, 8).map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>' : '');
}
function showErr(e, id) { msg(errHtml(e), 'bad', id); }

function chip(a) {
  var c = /^(Created|Restored|Imported)/.test(a) ? 'g' : /^(Deleted|Import undone)/.test(a) ? 'r' : /^Modified/.test(a) ? 'b' : /^Settings/.test(a) ? 'w' : '';
  return '<span class="chip ' + c + '">' + esc(a) + '</span>';
}
function countUp(el) {
  var n = +el.dataset.n;
  if (n < 2 || REDUCED) return;
  var t0 = null;
  (function f(t) { t0 = t0 || t; var p = Math.min(1, (t - t0) / 500); el.textContent = Math.round(n * p); if (p < 1) requestAnimationFrame(f); })(performance.now());
}
function debounce(fn, ms) { var t; return function () { var a = arguments, me = this; clearTimeout(t); t = setTimeout(function () { fn.apply(me, a); }, ms); }; }
function options(arr, selected, placeholder) {
  return (placeholder ? '<option value="">' + esc(placeholder) + '</option>' : '') +
    arr.map(function (x) { return '<option' + (x === selected ? ' selected' : '') + '>' + esc(x) + '</option>'; }).join('');
}
function busy(btn, on) { if (btn) btn.classList.toggle('busy', !!on); }
