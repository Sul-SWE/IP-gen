/* Admin sign in. Only one admin can be signed in at a time. */
(function () {
  var q = new URLSearchParams(location.search), next = q.get('next') || 'index.html';
  if (!/^[a-z]+\.html(#[a-z]+)?$/.test(next)) next = 'index.html';       // never redirect outside the tool
  var reasons = {
    session_replaced: ['Another admin signed in, so your session was ended. Sign in again to continue.', 'warn'],
    expired: ['Your session ended. Sign in again to continue.', 'info'],
    login_required: ['Sign in as admin to open that page.', 'info']
  };
  if (reasons[q.get('reason')]) msg(esc(reasons[q.get('reason')][0]), reasons[q.get('reason')][1]);
  $('#u').focus();

  function signIn(force) {
    var u = $('#u').value.trim(), p = $('#p').value;
    if (!u || !p) { msg('Type the username and the password.'); return; }
    busy($('#go'), true);
    API.call('POST', '/auth/login', { username: u, password: p, force: !!force }).then(function () {
      location.replace(next);
    }, function (e) {
      busy($('#go'), false);
      if (e.error === 'admin_busy') {
        msg(esc(e.message) + '<br>Last activity: <b>' + esc(e.last_seen || '') + '</b>.<div class="row" style="margin-top:8px"><button type="button" class="danger" id="force">Sign in anyway and end the other session</button></div>' +
          '<small>Do this only if you know the other engineer has finished. Unsaved work in the other session is lost.</small>', 'warn');
        $('#force').onclick = function () { signIn(true); };
        return;
      }
      showErr(e); $('#p').value = ''; $('#p').focus();
    });
  }
  $('#f').addEventListener('submit', function (e) { e.preventDefault(); signIn(false); });
})();
