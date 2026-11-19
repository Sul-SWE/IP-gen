<?php
/**
 * REST API (served at api/index.php/...). Read-only endpoints are public (viewer);
 * everything else needs the admin session cookie plus the X-CSRF-Token header.
 */

declare(strict_types=1);

final class Api
{
    private ?Db $db = null;
    private ?array $cfg = null;
    private ?array $session = null;
    private bool $sessionLoaded = false;
    private string $method;
    private string $path;

    public function __construct()
    {
        $this->method = strtoupper($_SERVER['REQUEST_METHOD'] ?? 'GET');
        $path = $_SERVER['PATH_INFO'] ?? '';
        if ($path === '') {   // some servers do not set PATH_INFO: take it from the URL
            $uri = parse_url($_SERVER['REQUEST_URI'] ?? '', PHP_URL_PATH) ?: '';
            $script = $_SERVER['SCRIPT_NAME'] ?? '';
            $path = str_starts_with($uri, $script) ? substr($uri, strlen($script)) : '';
        }
        $this->path = '/' . trim($path, '/');
    }

    /* ------------------------------------------------------------ plumbing */
    public static function configFile(): string { return __DIR__ . '/config.php'; }

    private function cfg(): array
    {
        if ($this->cfg === null) {
            if (!is_file(self::configFile())) {
                throw new ApiError(503, 'setup_required', 'The tool is not set up yet. Open the setup page to connect it to MySQL.');
            }
            $c = require self::configFile();
            $defaults = require __DIR__ . '/config.example.php';
            $this->cfg = array_replace($defaults, is_array($c) ? $c : []);
        }
        return $this->cfg;
    }

    private function db(): Db
    {
        if ($this->db === null) {
            try {
                $this->db = new Db($this->cfg()['db']);
            } catch (PDOException $e) {
                throw new ApiError(503, 'db_unavailable', 'Cannot connect to the MySQL database. Make sure MySQL is running (in XAMPP press Start next to MySQL), then reload the page.');
            }
        }
        return $this->db;
    }

    private function ip(): string { return (string)($_SERVER['REMOTE_ADDR'] ?? 'unknown'); }

    /** Every value the browser sent for the sign-in cookie (a browser may hold more than one, e.g. for different paths). */
    private function cookies(): array
    {
        $out = [];
        foreach (explode(';', (string)($_SERVER['HTTP_COOKIE'] ?? '')) as $part) {
            $kv = explode('=', trim($part), 2);
            if (count($kv) === 2 && $kv[0] === Auth::COOKIE && $kv[1] !== '') { $out[] = urldecode($kv[1]); }
        }
        if (!$out && isset($_COOKIE[Auth::COOKIE]) && is_string($_COOKIE[Auth::COOKIE])) { $out[] = $_COOKIE[Auth::COOKIE]; }
        return array_values(array_unique($out));
    }

    private function cookie(): ?string { return $this->cookies()[0] ?? null; }

    private function optionalAdmin(): ?array
    {
        if (!$this->sessionLoaded) {
            $this->sessionLoaded = true;
            // use the first cookie that belongs to a live session; report "session replaced" only if none is live
            $replaced = null;
            foreach ($this->cookies() as $token) {
                try {
                    $this->session = Auth::session($this->db(), $this->cfg(), $token);
                } catch (ApiError $e) { $replaced = $e; continue; }
                if ($this->session !== null) { break; }
            }
            if ($this->session === null && $replaced !== null) { throw $replaced; }
        }
        return $this->session;
    }

    private function requireAdmin(): array
    {
        $s = $this->optionalAdmin();
        if ($s === null) { throw new ApiError(401, 'login_required', 'Sign in as admin to do this.'); }
        if (!in_array($this->method, ['GET', 'HEAD', 'OPTIONS'], true) && !Auth::csrfOk($s, $_SERVER['HTTP_X_CSRF_TOKEN'] ?? null)) {
            throw new ApiError(403, 'csrf', 'The page is out of date. Reload it and try again.');
        }
        return $s;
    }

    private function setCookie(string $value, int $maxAge): void
    {
        // path '/': works whatever the folder is called (spaces, brackets, Arabic letters ...)
        setcookie(Auth::COOKIE, $value, ['expires' => $maxAge > 0 ? time() + $maxAge : time() - 3600, 'path' => '/',
            'httponly' => true, 'samesite' => 'Strict', 'secure' => (bool)($this->cfg['cookie_secure'] ?? false)]);
    }

    private static function headers(): void
    {
        header('Content-Type: application/json; charset=utf-8');
        header('Cache-Control: no-store');
        header("Content-Security-Policy: default-src 'none'; frame-ancestors 'none'");
        header('X-Content-Type-Options: nosniff');
        header('X-Frame-Options: DENY');
        header('Referrer-Policy: no-referrer');
    }

    private static function send($data, int $status = 200): void
    {
        http_response_code($status);
        self::headers();
        echo json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRESERVE_ZERO_FRACTION);
    }

    /* ------------------------------------------------------------ input validation (like the Pydantic models) */
    private function rawBody(): array
    {
        $raw = file_get_contents('php://input');
        if ($raw === '' || $raw === false) { return []; }
        $v = json_decode($raw, true);
        if (!is_array($v) || ($v !== [] && array_is_list($v))) { throw new ApiError(422, 'validation', 'Some values are missing or not valid.', ['body: must be a JSON object']); }
        return $v;
    }

    /**
     * spec: name => [type, options]; types: str, int, bool, dict_int, fields.
     * options: req (default true unless 'default' is given), null (allows null), min, max (length for str, value for int).
     */
    private function body(array $spec): array
    {
        return self::validate($this->rawBody(), $spec);
    }

    private static function validate(array $in, array $spec, string $prefix = ''): array
    {
        $errors = []; $out = [];
        foreach (array_keys($in) as $k) { if (!array_key_exists((string)$k, $spec)) { $errors[] = "$prefix$k: Extra inputs are not permitted"; } }
        foreach ($spec as $name => $o) {
            $type = $o[0];
            if (!array_key_exists($name, $in)) {
                if (array_key_exists('default', $o)) { $out[$name] = $o['default']; continue; }
                $errors[] = "$prefix$name: Field required"; continue;
            }
            $v = $in[$name];
            if ($v === null) {
                if (!empty($o['null'])) { $out[$name] = null; continue; }
                $errors[] = "$prefix$name: Input should not be empty"; continue;
            }
            switch ($type) {
                case 'str':
                    if (!is_string($v)) { $errors[] = "$prefix$name: Input should be a valid string"; break; }
                    $v = trim($v);
                    $len = Engine::len($v);
                    if (isset($o['max']) && $len > $o['max']) { $errors[] = "$prefix$name: String should have at most {$o['max']} characters"; break; }
                    if (isset($o['min']) && $len < $o['min']) { $errors[] = "$prefix$name: String should have at least {$o['min']} characters"; break; }
                    $out[$name] = $v; break;
                case 'int':
                    if (is_string($v) && preg_match('/^\s*-?\d+\s*$/', $v)) { $v = (int)$v; }
                    if (is_float($v) && floor($v) === $v) { $v = (int)$v; }
                    if (!is_int($v)) { $errors[] = "$prefix$name: Input should be a valid integer"; break; }
                    if (isset($o['min']) && $v < $o['min']) { $errors[] = "$prefix$name: Input should be greater than or equal to {$o['min']}"; break; }
                    if (isset($o['max']) && $v > $o['max']) { $errors[] = "$prefix$name: Input should be less than or equal to {$o['max']}"; break; }
                    $out[$name] = $v; break;
                case 'bool':
                    if (is_string($v) && in_array(strtolower($v), ['true', 'false', '1', '0'], true)) { $v = in_array(strtolower($v), ['true', '1'], true); }
                    if (is_int($v) && ($v === 0 || $v === 1)) { $v = $v === 1; }
                    if (!is_bool($v)) { $errors[] = "$prefix$name: Input should be a valid boolean"; break; }
                    $out[$name] = $v; break;
                case 'dict_int':
                    if (!is_array($v) || ($v !== [] && array_is_list($v))) { $errors[] = "$prefix$name: Input should be a valid dictionary"; break; }
                    $d = [];
                    foreach ($v as $k => $x) {
                        if (is_float($x) && floor($x) === $x) { $x = (int)$x; }
                        if (is_string($x) && preg_match('/^-?\d+$/', $x)) { $x = (int)$x; }
                        if (!is_int($x)) { $errors[] = "$prefix$name.$k: Input should be a valid integer"; continue; }
                        $d[(string)$k] = $x;
                    }
                    $out[$name] = $d; break;
                case 'fields':
                    if (!is_array($v) || !array_is_list($v)) { $errors[] = "$prefix$name: Input should be a valid list"; break; }
                    if (count($v) > 11) { $errors[] = "$prefix$name: List should have at most 11 items"; break; }
                    $list = [];
                    foreach ($v as $i => $item) {
                        if (!is_array($item)) { $errors[] = "$prefix$name.$i: Input should be an object"; continue; }
                        try {
                            $list[] = self::validate($item, ['field' => ['str', 'max' => 30], 'net' => ['str', 'max' => 1], 'a' => ['int', 'min' => 0, 'max' => 254],
                                'b' => ['int', 'min' => -254, 'max' => 254]], "$prefix$name.$i.");
                        } catch (ApiError $e) { $errors = array_merge($errors, $e->details); }
                    }
                    $out[$name] = $list; break;
            }
        }
        if ($errors) { throw new ApiError(422, 'validation', 'Some values are missing or not valid.', $errors); }
        return $out;
    }

    private static function qstr(string $name, string $default = '', int $max = 60, bool $required = false): string
    {
        $v = $_GET[$name] ?? null;
        if ($v === null) {
            if ($required) { throw new ApiError(422, 'validation', 'Some values are missing or not valid.', ["$name: Field required"]); }
            return $default;
        }
        if (!is_string($v) || Engine::len($v) > $max) { throw new ApiError(422, 'validation', 'Some values are missing or not valid.', ["$name: String should have at most $max characters"]); }
        return $v;
    }

    private static function qint(string $name, int $default, int $min, int $max): int
    {
        $v = $_GET[$name] ?? null;
        if ($v === null || $v === '') { return $default; }
        if (!is_string($v) || !preg_match('/^-?\d+$/', $v) || (int)$v < $min || (int)$v > $max) {
            throw new ApiError(422, 'validation', 'Some values are missing or not valid.', ["$name: must be a whole number from $min to $max"]);
        }
        return (int)$v;
    }

    private function actor(string $v): string { return Records::person($v, 'Your name'); }

    private const ACTOR = ['str', 'max' => 60];
    private const ACTING = ['actor' => ['str', 'max' => 60], 'version' => ['int', 'null' => true, 'default' => null]];
    private const GENERATE = ['facility' => ['str', 'max' => 8], 'well' => ['str', 'max' => 5], 'gcp' => ['str', 'max' => 40], 'vendor' => ['str', 'max' => 30], 'engineer' => ['str', 'max' => 60]];

    /* ------------------------------------------------------------ routing */
    public function handle(): void
    {
        try {
            [$fn, $args, $status] = $this->route();
            $out = $this->$fn(...$args);
            if ($out !== null) { self::send($out, $status); }
        } catch (ApiError $e) {
            if ($e->errCode === 'session_replaced') { $this->setCookie('', -1); }
            if ($this->db) { $this->db->rollback(); }
            self::send($e->body(), $e->status);
        } catch (Throwable $e) {   // never leak internals
            if ($this->db) { $this->db->rollback(); }
            @file_put_contents(__DIR__ . '/storage/error.log', date('c') . ' ' . get_class($e) . ': ' . $e->getMessage() . ' @ ' . basename($e->getFile()) . ':' . $e->getLine() . "\n", FILE_APPEND);
            // on the server computer itself, show what happened so it can be fixed; other computers only see a general message
            $detail = self::isLocal() ? [get_class($e) . ': ' . $e->getMessage() . ' (' . basename($e->getFile()) . ':' . $e->getLine() . ', PHP ' . PHP_VERSION . ')'] : [];
            self::send(['error' => 'server', 'message' => 'Something went wrong on the server. Nothing was changed.', 'details' => $detail], 500);
        }
    }

    private function route(): array
    {
        $m = $this->method; $p = $this->path;
        $routes = [
            ['GET', '#^/auth/me$#', 'me'], ['POST', '#^/auth/login$#', 'login'], ['POST', '#^/auth/logout$#', 'logout'], ['POST', '#^/auth/password$#', 'password'],
            ['GET', '#^/setup/status$#', 'setupStatus'], ['POST', '#^/setup$#', 'setup'],
            ['GET', '#^/config$#', 'config'], ['GET', '#^/dashboard$#', 'dashboard'], ['GET', '#^/ranges$#', 'ranges'], ['GET', '#^/records$#', 'listRecords'],
            ['POST', '#^/generate/preview$#', 'generatePreview'], ['GET', '#^/names/check$#', 'nameCheck'], ['POST', '#^/records$#', 'createRecord', 201],
            ['GET', '#^/records/(\d+)$#', 'getRecord'], ['POST', '#^/records/(\d+)/edit-preview$#', 'editPreview'], ['PATCH', '#^/records/(\d+)$#', 'updateRecord'],
            ['DELETE', '#^/records/(\d+)$#', 'trashRecord'], ['POST', '#^/records/(\d+)/restore$#', 'restoreRecord'], ['DELETE', '#^/records/(\d+)/permanent$#', 'purgeRecord'],
            ['GET', '#^/engineers/suggest$#', 'engineers'], ['GET', '#^/audit-log$#', 'auditLog'],
            ['POST', '#^/import/preview$#', 'importPreview'], ['POST', '#^/import/confirm$#', 'importConfirm'], ['GET', '#^/import/last$#', 'importLast'],
            ['POST', '#^/import/undo-last$#', 'importUndo'], ['GET', '#^/export$#', 'export'],
            ['GET', '#^/records/(\d+)/pmt$#', 'recordPmt'], ['GET', '#^/admin/pmt-template$#', 'pmtTemplate'],
            ['POST', '#^/admin/pmt-template$#', 'uploadPmtTemplate'], ['POST', '#^/admin/pmt-template/reset$#', 'resetPmtTemplate'],
            ['GET', '#^/admin/rules$#', 'adminRules'], ['POST', '#^/admin/facilities$#', 'addFacility', 201], ['PATCH', '#^/admin/facilities/(\d+)$#', 'patchFacility'],
            ['POST', '#^/admin/gcps$#', 'addGcp', 201], ['PATCH', '#^/admin/gcps/(\d+)$#', 'patchGcp'], ['POST', '#^/admin/vendors/check$#', 'checkVendor'],
            ['POST', '#^/admin/vendors$#', 'addVendor', 201], ['PATCH', '#^/admin/vendors/(\d+)$#', 'patchVendor'], ['POST', '#^/admin/blocks$#', 'addBlock', 201],
            ['POST', '#^/admin/blocks/(\d+)/activate$#', 'activateBlock'], ['DELETE', '#^/admin/blocks/(\d+)$#', 'deleteBlock'], ['PATCH', '#^/admin/settings$#', 'patchSettings'],
        ];
        $pathMatched = false;
        foreach ($routes as $r) {
            if (preg_match($r[1], $p, $mm)) {
                $pathMatched = true;
                if ($r[0] === $m) { return [$r[2], array_map('intval', array_slice($mm, 1)), $r[3] ?? 200]; }
            }
        }
        if ($pathMatched) { throw new ApiError(405, 'http', 'Method Not Allowed'); }
        throw new ApiError(404, 'not_found', 'Not Found');
    }

    /* ------------------------------------------------------------ setup (first run, from this computer only) */
    private static function isLocal(): bool
    {
        return in_array($_SERVER['REMOTE_ADDR'] ?? '', ['127.0.0.1', '::1', '::ffff:127.0.0.1'], true);
    }

    private function setupStatus(): array
    {
        return ['configured' => is_file(self::configFile()), 'local' => self::isLocal(), 'php' => PHP_VERSION,
            'extensions_ok' => extension_loaded('pdo_mysql') && extension_loaded('xmlreader') && extension_loaded('zlib') && extension_loaded('simplexml') && extension_loaded('dom')];
    }

    private function setup(): array
    {
        if (is_file(self::configFile())) { throw ApiError::conflict('The tool is already set up. To start again, delete server/config.php.', [], 'already_setup'); }
        if (!self::isLocal()) { throw new ApiError(403, 'forbidden', 'Setup can only be done on the computer that runs the server (open http://localhost/...).'); }
        $b = $this->body(['host' => ['str', 'max' => 100, 'default' => 'localhost'], 'port' => ['int', 'min' => 1, 'max' => 65535, 'default' => 3306],
            'user' => ['str', 'min' => 1, 'max' => 80], 'password' => ['str', 'max' => 200, 'default' => ''],
            'database' => ['str', 'max' => 64, 'default' => 'ipgen'], 'admin_password' => ['str', 'max' => 200]]);
        if (!preg_match('/^[A-Za-z0-9_]{1,64}$/D', $b['database'])) { throw ApiError::bad('The database name may only contain letters, digits and _.'); }
        $p = Auth::passwordProblem($b['admin_password']);
        if ($p !== '') { throw ApiError::bad('Website admin password: ' . $p); }
        $c = ['host' => $b['host'] === '' ? 'localhost' : $b['host'], 'port' => $b['port'], 'name' => $b['database'], 'user' => $b['user'], 'pass' => $b['password']];
        try {
            $root = new Db($c, false);
            $root->pdo->exec('CREATE DATABASE IF NOT EXISTS `' . $c['name'] . '` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci');
            $db = new Db($c);
        } catch (PDOException $e) {
            $msg = $e->getMessage();
            $hint = str_contains($msg, '1045') ? 'The MySQL user name or password is wrong.'
                : (str_contains($msg, '2002') || str_contains($msg, 'refused') ? 'MySQL is not running or the server/port is wrong. In XAMPP, press Start next to MySQL.' : 'MySQL refused the connection.');
            throw ApiError::bad("Could not connect to MySQL. $hint", [preg_replace('/\s+/', ' ', substr($msg, 0, 200))], 'db_connect');
        }
        // database/ipgen.sql: the tables and the starting rules (safe to run again: nothing is duplicated)
        $sqlFile = dirname(__DIR__) . '/database/ipgen.sql';
        foreach (array_filter(array_map('trim', explode(';', preg_replace('/--[^\n]*/', '', (string)file_get_contents($sqlFile))))) as $sql) {
            $db->pdo->exec($sql);
        }
        $existing = (int)$db->value('SELECT COUNT(*) FROM accounts');
        if (!$existing) {
            $db->q("INSERT INTO accounts (username, password_hash, role, active) VALUES ('admin', ?, 'admin', 1)", [Auth::hash($b['admin_password'])]);
        }
        $config = (require __DIR__ . '/config.example.php');
        $config['db'] = $c;
        $php = "<?php\n// Created by the setup page. Keep it private: it contains the MySQL password. Delete it to run setup again.\nreturn " . var_export($config, true) . ";\n";
        if (@file_put_contents(self::configFile(), $php, LOCK_EX) === false) {
            throw ApiError::bad('Could not save server/config.php. Make sure the folder is not read-only, then try again.', [], 'config_write');
        }
        @mkdir(__DIR__ . '/storage', 0770, true);
        return ['ok' => true, 'existing_data' => $existing > 0,
            'message' => $existing ? 'Connected to the existing database. Sign in with your existing admin password.' : 'Setup complete. Sign in as admin with the password you chose.'];
    }

    /* ------------------------------------------------------------ session */
    private function me(): array
    {
        $c = $this->cfg();
        $s = $this->optionalAdmin();
        if ($s === null) { return ['role' => 'viewer', 'viewer_can_see_worksheet' => (bool)$c['viewer_can_see_worksheet']]; }
        return ['role' => 'admin', 'csrf' => $s['csrf'], 'session_hours' => (int)$c['session_hours'], 'viewer_can_see_worksheet' => true];
    }

    private function login(): array
    {
        $b = $this->body(['username' => ['str', 'min' => 1, 'max' => 40], 'password' => ['str', 'min' => 1, 'max' => 200], 'force' => ['bool', 'default' => false]]);
        [$token, $csrf] = Auth::login($this->db(), $this->cfg(), $b['username'], $b['password'], $this->ip(), $b['force']);
        $this->setCookie($token, (int)$this->cfg()['session_hours'] * 3600);
        return ['role' => 'admin', 'csrf' => $csrf];
    }

    private function logout(): array
    {
        $this->cfg();
        foreach ($this->cookies() as $t) { Auth::logout($this->db(), $t, $this->ip()); }
        if (!$this->cookies()) { Auth::logout($this->db(), null, $this->ip()); }
        $this->setCookie('', -1);
        return ['ok' => true];
    }

    private function password(): array
    {
        $s = $this->requireAdmin();
        $b = $this->body(['current' => ['str', 'max' => 200], 'new' => ['str', 'max' => 200]]);
        Auth::changePassword($this->db(), $s, $b['current'], $b['new']);
        return ['ok' => true];
    }

    /* ------------------------------------------------------------ public reads */
    private function config(): array
    {
        $r = Rules::load($this->db());
        return [
            'facilities' => $r->activeFacilityCodes(),
            'gcps' => array_values(array_map(fn($g) => $g['code'], array_filter($r->gcps, fn($g) => $g['active']))),
            'vendors' => array_values(array_map(fn($v) => $v['name'], array_filter($r->vendors, fn($v) => $v['active']))),
            'warn_at' => $r->warnAt, 'mask' => $r->mask, 'columns' => Engine::columns(), 'ip_columns' => array_merge(Engine::ipFields(), ['Subnet Mask']),
            'viewer_can_see_worksheet' => (bool)$this->cfg()['viewer_can_see_worksheet'],
        ];
    }

    private function dashboard(): array { $this->cfg(); return Dashboard::build($this->db()); }
    private function ranges(): array { $this->cfg(); return ['ranges' => Dashboard::ranges($this->db())]; }

    private function listRecords(): array
    {
        $s = $this->optionalAdmin();
        if ($s === null && !$this->cfg()['viewer_can_see_worksheet']) { throw new ApiError(403, 'forbidden', 'The worksheet is only available to the admin.'); }
        $out = Records::search($this->db(), self::qstr('q'), self::qstr('field', 'all', 20), self::qstr('status', 'active', 20),
            self::qint('page', 1, 1, PHP_INT_MAX), self::qint('size', 100, 1, 500), self::qstr('sort', 'old', 10) === 'new');
        $out['counts'] = Records::counts($this->db());
        return $out;
    }

    /* ------------------------------------------------------------ generation and records (admin) */
    private function generatePreview(): array
    {
        $this->requireAdmin();
        $b = $this->body(self::GENERATE);
        return Records::previewNew($this->db(), $b['facility'], $b['well'], $b['gcp'], $b['vendor'], $b['engineer']);
    }

    private function nameCheck(): array
    {
        $this->requireAdmin();
        $name = strtoupper(trim(self::qstr('name', '', 40, true)));
        $where = Records::buildIndex($this->db())['names'][$name] ?? null;
        return ['available' => $where === null, 'where' => $where ?? ''];
    }

    private function createRecord(): array
    {
        $this->requireAdmin();
        $b = $this->body(self::GENERATE + ['signature' => ['str', 'max' => 64]]);
        $db = $this->db();
        return $db->write(fn(Db $db) => Records::serializeOne($db, Records::create($db, $b)));
    }

    private function getRecord(int $id): array { $this->requireAdmin(); return Records::serializeOne($this->db(), Records::get($this->db(), $id)); }

    private function editPreview(int $id): array
    {
        $this->requireAdmin();
        $b = $this->body(['gcp' => ['str', 'max' => 40], 'vendor' => ['str', 'max' => 30]]);
        return Records::regenPreview($this->db(), Records::get($this->db(), $id), $b['gcp'], $b['vendor']);
    }

    private function updateRecord(int $id): array
    {
        $this->requireAdmin();
        $o = ['null' => true, 'default' => null];
        $b = $this->body(self::ACTING + ['name' => ['str', 'max' => 40] + $o, 'engineer' => ['str', 'max' => 60] + $o, 'date' => ['str', 'max' => 20] + $o,
            'gcp' => ['str', 'max' => 40] + $o, 'vendor' => ['str', 'max' => 30] + $o, 'signature' => ['str', 'max' => 64] + $o]);
        return $this->db()->write(function (Db $db) use ($id, $b) {
            [$r, $regen] = Records::update($db, $id, $b);
            return Records::serializeOne($db, $r) + ['regenerated' => $regen];
        });
    }

    private function trashRecord(int $id): array
    {
        $this->requireAdmin();
        $b = $this->body(self::ACTING);
        return $this->db()->write(fn(Db $db) => Records::serializeOne($db, Records::trash($db, $id, $b['version'], $b['actor'])));
    }

    private function restoreRecord(int $id): array
    {
        $this->requireAdmin();
        $b = $this->body(self::ACTING);
        return $this->db()->write(fn(Db $db) => Records::serializeOne($db, Records::restore($db, $id, $b['version'], $b['actor'])));
    }

    private function purgeRecord(int $id): array
    {
        $this->requireAdmin();
        $b = $this->body(self::ACTING);
        return ['name' => $this->db()->write(fn(Db $db) => Records::purge($db, $id, $b['version'], $b['actor']))];
    }

    private function engineers(): array { $this->requireAdmin(); return ['names' => Records::suggestEngineers($this->db(), self::qstr('q', '', 40))]; }

    private function auditLog(): array
    {
        $this->requireAdmin();
        $db = $this->db();
        $q = trim(self::qstr('q')); $page = self::qint('page', 1, 1, PHP_INT_MAX); $size = self::qint('size', 100, 1, 200);
        $where = ''; $p = [];
        if ($q !== '') {
            $pat = Records::like(function_exists('mb_strtolower') ? mb_strtolower($q, 'UTF-8') : strtolower($q));
            $where = "WHERE (LOWER(engineer_name) LIKE ? ESCAPE '!' OR LOWER(action) LIKE ? ESCAPE '!' OR LOWER(record_name) LIKE ? ESCAPE '!' OR LOWER(details) LIKE ? ESCAPE '!')";
            $p = [$pat, $pat, $pat, $pat];
        }
        $total = (int)$db->value("SELECT COUNT(*) FROM audit_log $where", $p);
        $pages = max(1, intdiv($total + $size - 1, $size));
        $page = min($page, $pages);
        $off = ($page - 1) * $size;
        $rows = $db->all("SELECT * FROM audit_log $where ORDER BY id DESC LIMIT $size OFFSET $off", $p);
        return ['items' => array_map(fn($x) => ['at' => fmt_dt($x['at']), 'role' => $x['role'], 'who' => $x['engineer_name'], 'action' => $x['action'],
            'name' => $x['record_name'], 'details' => $x['details']], $rows), 'total' => $total, 'page' => $page, 'pages' => $pages, 'counts' => Records::counts($db)];
    }

    /* ------------------------------------------------------------ Excel (admin) */
    private function importPreview(): array
    {
        $this->requireAdmin();
        $f = $_FILES['file'] ?? null;
        if (!$f || is_array($f['name'])) {
            $tooBig = (int)($_SERVER['CONTENT_LENGTH'] ?? 0) > Importer::MAX_BYTES;
            if ($tooBig) { throw new ApiError(413, 'too_large', 'This file is larger than 5 MB. Nothing was imported.'); }
            throw new ApiError(422, 'validation', 'Some values are missing or not valid.', ['file: Field required']);
        }
        if (in_array($f['error'], [UPLOAD_ERR_INI_SIZE, UPLOAD_ERR_FORM_SIZE], true) || (int)$f['size'] > Importer::MAX_BYTES) {
            throw new ApiError(413, 'too_large', 'This file is larger than 5 MB. Nothing was imported.');
        }
        $name = (string)$f['name'];
        $data = $f['error'] === UPLOAD_ERR_OK ? (string)file_get_contents($f['tmp_name']) : '';
        if ($f['error'] !== UPLOAD_ERR_OK && $f['error'] !== UPLOAD_ERR_NO_FILE) {
            throw ApiError::bad('The file could not be uploaded. Try again.', [], 'upload_failed');
        }
        return Importer::preview($this->db(), $data, $name);
    }

    private function importConfirm(): array
    {
        $this->requireAdmin();
        $b = $this->body(['token' => ['str', 'max' => 80], 'actor' => self::ACTOR]);
        return $this->db()->write(fn(Db $db) => Importer::confirm($db, $b['token'], $b['actor']));
    }

    private function importLast(): array { $this->requireAdmin(); return ['last' => Importer::lastImport($this->db())]; }

    private function importUndo(): array
    {
        $this->requireAdmin();
        $b = $this->body(['actor' => self::ACTOR, 'batch' => ['str', 'max' => 40, 'null' => true, 'default' => null]]);
        return $this->db()->write(fn(Db $db) => Importer::undoLast($db, $b['actor'], $b['batch']));
    }

    private static function sendXlsx(string $bin, string $name, array $extra = []): void
    {
        header('Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
        header('Content-Disposition: attachment; filename="' . $name . '"');
        foreach ($extra as $h) { header($h); }
        header('Cache-Control: no-store');
        header('X-Content-Type-Options: nosniff');
        header('Content-Length: ' . strlen($bin));
        echo $bin;
    }

    private function export(): ?array
    {
        $this->requireAdmin();
        [$bin, $name, $n] = Importer::export($this->db());
        if (!$n) { throw ApiError::bad('There are no active records to export.', [], 'nothing_to_export'); }
        self::sendXlsx($bin, $name, ['X-Record-Count: ' . $n]);
        return null;
    }

    /* ------------------------------------------------------------ PMT file (admin) */
    private function recordPmt(int $id): ?array
    {
        $this->requireAdmin();
        $db = $this->db();
        $rec = Records::serializeOne($db, Records::get($db, $id));
        $path = Pmt::templatePath();
        if (!is_file($path)) { throw ApiError::bad('No PMT template was found. Upload one in Settings.', [], 'no_template'); }
        $bin = Pmt::fill((string)file_get_contents($path), Pmt::values($rec, $db->today()));
        self::sendXlsx($bin, Pmt::fileName($rec['name']));
        return null;
    }

    private function pmtTemplate(): ?array
    {
        $this->requireAdmin();
        $path = Pmt::templatePath();
        if (!is_file($path)) { throw ApiError::bad('No PMT template was found.', [], 'no_template'); }
        self::sendXlsx((string)file_get_contents($path), 'PMT-template.xlsx');
        return null;
    }

    private function uploadPmtTemplate(): array
    {
        $this->requireAdmin();
        $who = $this->actor((string)($_POST['actor'] ?? ''));
        $f = $_FILES['file'] ?? null;
        if (!$f || is_array($f['name']) || $f['error'] === UPLOAD_ERR_NO_FILE) { throw new ApiError(422, 'validation', 'Choose the template file.', ['file: Field required']); }
        if (in_array($f['error'], [UPLOAD_ERR_INI_SIZE, UPLOAD_ERR_FORM_SIZE], true) || (int)$f['size'] > Pmt::MAX_BYTES) {
            throw new ApiError(413, 'too_large', 'The template is larger than 2 MB.');
        }
        if ($f['error'] !== UPLOAD_ERR_OK) { throw ApiError::bad('The file could not be uploaded. Try again.', [], 'upload_failed'); }
        if (!preg_match('/\.xlsx$/i', (string)$f['name'])) { throw ApiError::bad('The template must be an Excel file (.xlsx).', [], 'wrong_type'); }
        $data = (string)file_get_contents($f['tmp_name']);
        $fields = Pmt::check($data);
        @mkdir(__DIR__ . '/storage', 0770, true);
        if (@file_put_contents(__DIR__ . '/storage/pmt-template.xlsx', $data, LOCK_EX) === false) {
            throw ApiError::bad('Could not save the template. Make sure the server folder is not read-only.', [], 'save_failed');
        }
        $db = $this->db();
        $db->write(fn(Db $db) => $this->log($db, $who, 'PMT template', 'New template uploaded (' . count($fields) . ' fields: ' . implode(', ', $fields) . ')'));
        return ['ok' => true, 'fields' => $fields, 'custom' => true];
    }

    private function resetPmtTemplate(): array
    {
        $this->requireAdmin();
        $b = $this->body(['actor' => self::ACTOR]);
        $who = $this->actor($b['actor']);
        if (Pmt::isCustom()) { @unlink(__DIR__ . '/storage/pmt-template.xlsx'); }
        $db = $this->db();
        $db->write(fn(Db $db) => $this->log($db, $who, 'PMT template', 'Back to the default template'));
        return ['ok' => true, 'custom' => false, 'fields' => Pmt::check((string)file_get_contents(Pmt::templatePath()))];
    }

    /* ------------------------------------------------------------ settings / admin panel */
    private static function blockJson(array $b): array
    {
        return ['id' => $b['id'], 'seq' => $b['seq'], 'status' => $b['status'], 'octets' => (object)$b['octets'],
            'activated_at' => fmt_dt($b['activated_at']), 'created_at' => fmt_dt($b['created_at'])];
    }

    private function log(Db $db, string $who, string $what, string $details): void { Records::addLog($db, $who, 'Settings changed', $what, $details); }

    private static function octs(array $o): string
    {
        ksort($o);
        return '{' . implode(', ', array_map(fn($k, $v) => "'$k': $v", array_keys($o), $o)) . '}';
    }

    private function adminRules(): array
    {
        $this->requireAdmin();
        $db = $this->db();
        $rules = Rules::load($db);
        $usage = [];
        foreach (Dashboard::ranges($db, $rules) as $r) { $usage[$r['gcp'] . '|' . $r['vendor']] = $r; }
        $gcps = [];
        foreach ($rules->gcps as $g) {
            $rng = [];
            foreach ($rules->vendors as $v) {
                $blocks = array_values(array_map(fn($b) => self::blockJson($b), array_filter($rules->blocks, fn($b) => $b['gcp_id'] === $g['id'] && $b['vendor_id'] === $v['id'])));
                $u = $usage[$g['code'] . '|' . $v['name']] ?? [];
                $rng[] = ['vendor' => $v['name'], 'vendor_id' => $v['id'], 'vendor_active' => $v['active'], 'blocks' => $blocks,
                    'used' => $u['used'] ?? 0, 'max' => $u['max'] ?? 0, 'state' => $u['state'] ?? 'none'];
            }
            $gcps[] = $g + ['ranges' => $rng];
        }
        return [
            'facilities' => $rules->facilities, 'gcps' => $gcps,
            'vendors' => array_map(fn($v) => ['id' => $v['id'], 'name' => $v['name'], 'capacity' => $v['capacity'], 'octets' => (object)$v['octets'],
                'fields' => $v['fields'], 'active' => $v['active']], $rules->vendors),
            'settings' => ['warn_at' => (int)round($rules->warnAt * 100), 'mask' => $rules->mask],
            'pmt' => self::pmtInfo(),
            'ip_fields' => Engine::ipFields(), 'device_fields' => Engine::UNIQ, 'infra_fields' => Engine::INFRA, 'nets' => Engine::NETS,
        ];
    }

    private static function pmtInfo(): array
    {
        $path = Pmt::templatePath();
        try { $fields = is_file($path) ? Pmt::check((string)file_get_contents($path)) : []; } catch (ApiError $e) { $fields = []; }
        return ['custom' => Pmt::isCustom(), 'fields' => $fields, 'all_fields' => Pmt::fields()];
    }

    private function addFacility(): array
    {
        $this->requireAdmin();
        $b = $this->body(['code' => ['str', 'max' => 8], 'actor' => self::ACTOR]);
        $who = $this->actor($b['actor']);
        return $this->db()->write(function (Db $db) use ($b, $who) {
            $f = Rules::addFacility($db, $b['code']);
            $this->log($db, $who, "Facility {$f['code']}", 'Added');
            return $f;
        });
    }

    private function patchFacility(int $id): array
    {
        $this->requireAdmin();
        $b = $this->body(['active' => ['bool'], 'actor' => self::ACTOR]);
        $who = $this->actor($b['actor']);
        return $this->db()->write(function (Db $db) use ($id, $b, $who) {
            $f = Rules::setFacilityActive($db, $id, $b['active']);
            $this->log($db, $who, "Facility {$f['code']}", $b['active'] ? 'Enabled' : 'Disabled for new records');
            return ['id' => $f['id'], 'active' => $f['active']];
        });
    }

    private function addGcp(): array
    {
        $this->requireAdmin();
        $b = $this->body(['code' => ['str', 'max' => 40], 'octet1' => ['int', 'min' => 0, 'max' => 255], 'octet2' => ['int', 'min' => 0, 'max' => 255],
            'rtu_vlan' => ['int', 'min' => 1, 'max' => 4094], 'plc_vlan' => ['int', 'min' => 1, 'max' => 4094], 'actor' => self::ACTOR]);
        $who = $this->actor($b['actor']);
        return $this->db()->write(function (Db $db) use ($b, $who) {
            $g = Rules::addGcp($db, $b['code'], $b['octet1'], $b['octet2'], $b['rtu_vlan'], $b['plc_vlan']);
            $this->log($db, $who, "GCP & Ring {$g['code']}", "Added: {$g['octet1']}.{$g['octet2']}.x.x, VLAN {$g['rtu_vlan']} / {$g['plc_vlan']}");
            return ['id' => $g['id'], 'code' => $g['code']];
        });
    }

    private function patchGcp(int $id): array
    {
        $this->requireAdmin();
        $o = ['null' => true, 'default' => null];
        $b = $this->body(['rtu_vlan' => ['int', 'min' => 1, 'max' => 4094] + $o, 'plc_vlan' => ['int', 'min' => 1, 'max' => 4094] + $o, 'active' => ['bool'] + $o, 'actor' => self::ACTOR]);
        $who = $this->actor($b['actor']);
        return $this->db()->write(function (Db $db) use ($id, $b, $who) {
            $g = Rules::updateGcp($db, $id, $b['rtu_vlan'], $b['plc_vlan'], $b['active']);
            $parts = [];
            if ($b['rtu_vlan'] !== null || $b['plc_vlan'] !== null) { $parts[] = "VLAN {$g['rtu_vlan']} / {$g['plc_vlan']} (applies to new records)"; }
            if ($b['active'] !== null) { $parts[] = $b['active'] ? 'Enabled' : 'Disabled for new records'; }
            $this->log($db, $who, "GCP & Ring {$g['code']}", $parts ? implode('; ', $parts) : 'No change');
            return ['id' => $g['id']];
        });
    }

    private const VENDOR = ['name' => ['str', 'max' => 30], 'capacity' => ['int', 'min' => 1, 'max' => 254], 'octets' => ['dict_int'], 'fields' => ['fields'],
        'actor' => ['str', 'max' => 60, 'default' => '']];

    private function checkVendor(): array
    {
        $this->requireAdmin();
        $b = $this->body(self::VENDOR);
        try {
            [$rule, $octs] = Rules::parseVendor($b['name'], $b['capacity'], $b['octets'], $b['fields']);
        } catch (ApiError $e) {
            return ['ok' => false, 'message' => $e->getMessage(), 'errors' => $e->details];
        }
        $blk = ['gcp' => 'EXAMPLE', 'octet1' => 10, 'octet2' => 1, 'octets' => $octs, 'rule' => $rule, 'rtu_vlan' => '', 'plc_vlan' => '', 'mask' => '255.255.255.0'];
        $ns = array_values(array_unique([1, 2, $rule['capacity']]));
        sort($ns);
        $ipf = array_flip(Engine::ipFields());
        $sample = array_map(fn($n) => ['n' => $n, 'ips' => array_intersect_key(Engine::build($blk, $n), $ipf)], $ns);
        return ['ok' => true, 'errors' => [], 'sample' => $sample];
    }

    private function addVendor(): array
    {
        $this->requireAdmin();
        $b = $this->body(self::VENDOR);
        $who = $this->actor($b['actor']);
        return $this->db()->write(function (Db $db) use ($b, $who) {
            $v = Rules::addVendor($db, $b['name'], $b['capacity'], $b['octets'], $b['fields']);
            $this->log($db, $who, "Vendor {$v['name']}", "Added: capacity {$v['capacity']}, third octets " . self::octs($v['octets']));
            return ['id' => $v['id'], 'name' => $v['name']];
        });
    }

    private function patchVendor(int $id): array
    {
        $this->requireAdmin();
        $b = $this->body(['active' => ['bool'], 'actor' => self::ACTOR]);
        $who = $this->actor($b['actor']);
        return $this->db()->write(function (Db $db) use ($id, $b, $who) {
            $v = Rules::setVendorActive($db, $id, $b['active']);
            $this->log($db, $who, "Vendor {$v['name']}", $b['active'] ? 'Enabled' : 'Disabled for new records');
            return ['id' => $v['id'], 'active' => $v['active']];
        });
    }

    private function addBlock(): array
    {
        $this->requireAdmin();
        $b = $this->body(['gcp_id' => ['int'], 'vendor_id' => ['int'], 'octets' => ['dict_int'], 'actor' => self::ACTOR]);
        $who = $this->actor($b['actor']);
        return $this->db()->write(function (Db $db) use ($b, $who) {
            $blk = Rules::addPlannedBlock($db, $b['gcp_id'], $b['vendor_id'], $b['octets']);
            $this->log($db, $who, "{$blk['gcp']['code']} / {$blk['vendor']['name']}", "Block {$blk['seq']} added as {$blk['status']}, third octets " . self::octs($blk['octets']));
            return self::blockJson($blk);
        });
    }

    private function activateBlock(int $id): array
    {
        $this->requireAdmin();
        $b = $this->body(['actor' => self::ACTOR]);
        $who = $this->actor($b['actor']);
        return $this->db()->write(function (Db $db) use ($id, $who) {
            [$blk, $old] = Rules::activateBlock($db, $id);
            $this->log($db, $who, "{$blk['gcp']['code']} / {$blk['vendor']['name']}", "Block {$blk['seq']} activated (third octets " . self::octs($blk['octets']) . ')'
                . ($old ? "; block {$old['seq']} retired, its addresses stay reserved" : ''));
            return self::blockJson($blk);
        });
    }

    private function deleteBlock(int $id): array
    {
        $this->requireAdmin();
        $b = $this->body(['actor' => self::ACTOR]);
        $who = $this->actor($b['actor']);
        return $this->db()->write(function (Db $db) use ($id, $who) {
            $blk = Rules::removePlannedBlock($db, $id);
            $this->log($db, $who, "{$blk['gcp']['code']} / {$blk['vendor']['name']}", "Planned block {$blk['seq']} removed");
            return ['ok' => true];
        });
    }

    private function patchSettings(): array
    {
        $this->requireAdmin();
        $b = $this->body(['warn_at' => ['int', 'min' => 50, 'max' => 99], 'actor' => self::ACTOR]);
        $who = $this->actor($b['actor']);
        return $this->db()->write(function (Db $db) use ($b, $who) {
            Rules::setSetting($db, 'warn_at', (string)($b['warn_at'] / 100));
            $this->log($db, $who, 'Warning threshold', "Set to {$b['warn_at']}%");
            return ['warn_at' => $b['warn_at']];
        });
    }
}
