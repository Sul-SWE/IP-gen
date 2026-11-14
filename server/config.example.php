<?php
// The setup page creates server/config.php from this layout. Never commit config.php.
return [
    'db' => ['host' => 'localhost', 'port' => 3306, 'name' => 'ipgen', 'user' => 'root', 'pass' => ''],
    'session_hours' => 8,             // admin is signed out after this many hours without activity
    'admin_idle_minutes' => 5,        // another admin may sign in without "take over" when the current one is idle this long
    'login_max_fails' => 5,
    'login_window_minutes' => 15,
    'cookie_secure' => false,         // true when the site is served over HTTPS
    'viewer_can_see_worksheet' => true,
];
