<?php
// Router for PHP's built-in web server (tests and quick trials):  php -S localhost:8000 server/dev-router.php
// It applies the same rules as the .htaccess files used by Apache / XAMPP.
$path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH) ?: '/';
if (preg_match('#^/(server|tests)(/|$)|/\.#', $path)) { http_response_code(404); echo 'Not found'; return true; }
if (str_starts_with($path, '/api/index.php')) { return false; }
if (preg_match('#\.html$#', $path) || $path === '/') {
    header("Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'");
    header('X-Content-Type-Options: nosniff');
    header('X-Frame-Options: DENY');
    header('Cache-Control: no-cache');
}
return false;
