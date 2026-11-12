/* The only place that talks to the server. Every change sends the CSRF token of the admin session. */
var API = {
  csrf: '',
  role: 'viewer',
  me: null,

  call: function (method, url, body, isForm) {
    var opt = { method: method, credentials: 'same-origin', headers: {} };
    if (method !== 'GET' && API.csrf) opt.headers['X-CSRF-Token'] = API.csrf;
    if (isForm) opt.body = body;
    else if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
    return fetch('/api' + url, opt).then(function (res) {
      return res.text().then(function (text) {
        var data = null;
        try { data = text ? JSON.parse(text) : null; } catch (e) { data = null; }
        if (res.ok) return data;
        var err = data && data.error ? data : { error: 'http', message: 'The server answered with an error (' + res.status + ').', details: [] };
        err.status = res.status;
        if (res.status === 401 && API.role === 'admin' && (err.error === 'session_replaced' || err.error === 'login_required')) {
          API.signedOut(err.error);   // the admin session ended: go to the sign-in page
        }
        throw err;
      });
    }, function () {
      throw { error: 'network', status: 0, message: 'Cannot reach the server. Check that it is running, then try again.', details: [] };
    });
  },
  get: function (url) { return API.call('GET', url); },
  post: function (url, body) { return API.call('POST', url, body === undefined ? {} : body); },
  patch: function (url, body) { return API.call('PATCH', url, body); },
  del: function (url, body) { return API.call('DELETE', url, body); },
  upload: function (url, file) { var f = new FormData(); f.append('file', file, file.name); return API.call('POST', url, f, true); },

  // file download through fetch, so the admin cookie and errors are handled like any other call
  download: function (url) {
    return fetch('/api' + url, { credentials: 'same-origin' }).then(function (res) {
      if (!res.ok) return res.json().then(function (e) { e.status = res.status; throw e; });
      var name = (/filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') || '') || [])[1] || 'export.xlsx';
      var count = +res.headers.get('X-Record-Count') || 0;
      return res.blob().then(function (blob) {
        var a = document.createElement('a'), href = URL.createObjectURL(blob);
        a.href = href; a.download = name; document.body.appendChild(a); a.click(); a.remove();
        setTimeout(function () { URL.revokeObjectURL(href); }, 4000);
        return { name: name, count: count };
      });
    });
  },

  signedOut: function (reason) {
    var page = location.pathname.split('/').pop() || 'index.html';
    location.replace('login.html?reason=' + encodeURIComponent(reason || 'expired') + '&next=' + encodeURIComponent(page + location.hash));
  }
};
