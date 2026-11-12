/* Browser storage (IndexedDB). One state object: records, log, seq, lastImport.
   update() reads, changes and writes inside ONE transaction, so two open tabs can never overwrite each other.
   (Prototype only: the full-stack version moves this to the server and database.) */
function norm(s) {
  s = s || {};
  var r = (Array.isArray(s.records) ? s.records : []).filter(function (x) { return x && typeof x === 'object' && x.ips && typeof x.ips === 'object'; }), mx = 0;
  r.forEach(function (x) { if (x.id > mx) mx = x.id; });
  return {
    records: r,
    log: Array.isArray(s.log) ? s.log : [],
    seq: Math.max(mx + 1, Number.isInteger(s.seq) && s.seq > 0 ? s.seq : 1),
    lastImport: s.lastImport && Array.isArray(s.lastImport.ids) ? s.lastImport : null
  };
}
var DB = {
  open: function () {
    return new Promise(function (ok, er) {
      if (!window.indexedDB) return er(new Error('no storage'));
      var q = indexedDB.open('iptool', 1);
      q.onupgradeneeded = function () { q.result.createObjectStore('kv'); };
      q.onsuccess = function () { ok(q.result); };
      q.onerror = function () { er(q.error); };
    });
  },
  load: function () {
    return this.open().then(function (d) {
      return new Promise(function (ok, er) {
        var g = d.transaction('kv').objectStore('kv').get('s');
        g.onsuccess = function () { ok(norm(g.result)); };
        g.onerror = function () { er(g.error); };
      });
    });
  },
  // fn(state) changes the state and returns a result; return {err:'...'} to cancel without writing
  update: function (fn) {
    return this.open().then(function (d) {
      return new Promise(function (ok, er) {
        var t = d.transaction('kv', 'readwrite'), o = t.objectStore('kv'), g = o.get('s'), st, res;
        g.onsuccess = function () {
          st = norm(g.result);
          try { res = fn(st) || {}; } catch (e) { t.abort(); return er(e); }
          if (res.err) { t.abort(); return ok(res); }
          if (st.log.length > 5000) st.log.length = 5000;
          o.put(st, 's');
        };
        t.oncomplete = function () { res.s = st; ok(res); };
        t.onerror = function () { er(t.error); };
      });
    });
  }
};
