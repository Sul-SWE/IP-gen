/* First-time setup: connects to MySQL, creates the tables and the admin account, saves server/config.php. */
(function () {
  API.get('/setup/status').then(function (s) {
    if (s.configured) { msg('The tool is already set up. <a href="login.html">Go to the sign-in page</a>.', 'info'); $('#go').disabled = true; return; }
    if (!s.local) { msg('Setup can only be done on the computer that runs the server. Open the tool there with <b>http://localhost/...</b>', 'warn'); $('#go').disabled = true; return; }
    if (!s.extensions_ok) { msg('A PHP extension is missing (pdo_mysql, xmlreader, simplexml, dom or zlib). Enable it in php.ini and restart Apache.', 'warn'); }
    $('#pass').focus();
  }, function (e) { showErr(e); });

  $('#f').addEventListener('submit', function (e) {
    e.preventDefault();
    var a1 = $('#ap1').value, a2 = $('#ap2').value, port = $('#port').value.trim();
    if (!$('#user').value.trim()) return msg('Type the MySQL user (in XAMPP it is <b>root</b>).');
    if (!/^\d{1,5}$/.test(port)) return msg('The port must be a number (usually 3306).');
    if (a1.length < 8) return msg('The admin password must be at least 8 characters.');
    if (a1 !== a2) return msg('The two admin passwords are not the same.');
    busy($('#go'), true); clearMsg();
    API.post('/setup', { host: $('#host').value.trim() || 'localhost', port: +port, user: $('#user').value.trim(), password: $('#pass').value,
      database: $('#dbname').value.trim() || 'ipgen', admin_password: a1 })
    .then(function (r) {
      msg(esc(r.message) + ' Opening the sign-in page...', 1);
      setTimeout(function () { location.replace('login.html'); }, 1500);
    }, function (e) { busy($('#go'), false); showErr(e); });
  });
})();
