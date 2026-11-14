<?php
/**
 * Admin sign-in: password hashing, server-side sessions, one admin at a time, CSRF and login rate limit.
 * Viewers need no account: read-only endpoints are public inside the network the tool is served on.
 */

declare(strict_types=1);

final class Auth
{
    public const COOKIE = 'ipgen_session';

    private static function sid(string $token): string { return hash('sha256', $token); }
    private static function token(int $bytes = 32): string { return rtrim(strtr(base64_encode(random_bytes($bytes)), '+/', '-_'), '='); }

    public static function passwordProblem(string $pw): string { return strlen($pw) >= 8 ? '' : 'The password must be at least 8 characters.'; }
    public static function hash(string $pw): string { return password_hash($pw, PASSWORD_DEFAULT); }

    private static function ago(Db $db, int $seconds): string
    {
        return date('Y-m-d H:i:s', strtotime($db->now()) - $seconds);
    }

    /** Failed sign-ins per client IP inside a sliding window. */
    private static function checkLimit(Db $db, array $cfg, string $ip): void
    {
        $window = (int)$cfg['login_window_minutes'] * 60;
        $db->q('DELETE FROM login_failures WHERE at < ?', [self::ago($db, $window)]);
        $rows = $db->all('SELECT at FROM login_failures WHERE ip = ? ORDER BY at', [$ip]);
        if (count($rows) >= (int)$cfg['login_max_fails']) {
            $first = strtotime($rows[0]['at']);
            $wait = max(1, intdiv($window - (strtotime($db->now()) - $first), 60) + 1);
            throw new ApiError(429, 'too_many_attempts', "Too many failed sign-ins. Try again in about $wait minute(s).");
        }
    }

    public static function login(Db $db, array $cfg, string $username, string $password, string $ip, bool $force): array
    {
        self::checkLimit($db, $cfg, $ip);
        $acc = $db->one('SELECT * FROM accounts WHERE username = ? AND active = 1', [trim($username)]);
        // an unknown user costs the same time as a wrong password
        $ok = $acc ? password_verify($password, $acc['password_hash']) : (password_verify($password, self::hash(random_bytes(8))) && false);
        if (!$ok) {
            $db->q('INSERT INTO login_failures (ip, at) VALUES (?, ?)', [$ip, $db->now()]);
            throw new ApiError(401, 'bad_credentials', 'Wrong username or password.');
        }
        $db->q('DELETE FROM login_failures WHERE ip = ?', [$ip]);
        if (password_needs_rehash($acc['password_hash'], PASSWORD_DEFAULT)) {
            $db->q('UPDATE accounts SET password_hash = ? WHERE id = ?', [self::hash($password), $acc['id']]);
        }
        // two sign-ins at the same moment are handled one after the other
        return $db->write(function (Db $db) use ($cfg, $acc, $ip, $force) {
            $now = $db->now();
            $db->q('DELETE FROM sessions WHERE last_seen < ?', [self::ago($db, 2 * 86400)]);
            $live = $db->all("SELECT * FROM sessions WHERE ended_reason = '' AND last_seen >= ?", [self::ago($db, (int)$cfg['session_hours'] * 3600)]);
            $idleLimit = self::ago($db, (int)$cfg['admin_idle_minutes'] * 60);
            $busy = array_filter($live, fn($s) => $s['last_seen'] >= $idleLimit);
            if ($busy && !$force) {
                $last = max(array_map(fn($s) => $s['last_seen'], $busy));
                throw new ApiError(409, 'admin_busy', 'Another admin is signed in right now. Only one admin can work at a time, so that two people never change the data together.',
                    [], ['last_seen' => substr($last, 0, 16)]);
            }
            $db->q("UPDATE sessions SET ended_reason = 'replaced' WHERE ended_reason = ''");
            $token = self::token();
            $csrf = self::token(24);
            $db->q('INSERT INTO sessions (id, account_id, csrf, created_at, last_seen, ip, ended_reason) VALUES (?, ?, ?, ?, ?, ?, \'\')',
                [self::sid($token), $acc['id'], $csrf, $now, $now, substr($ip, 0, 45)]);
            return [$token, $csrf];
        });
    }

    /** The live admin session of this cookie, or null. Throws 401 session_replaced when another sign-in took over. */
    public static function session(Db $db, array $cfg, ?string $token): ?array
    {
        if ($token === null || $token === '') { return null; }
        $s = $db->one('SELECT * FROM sessions WHERE id = ?', [self::sid($token)]);
        if (!$s) { return null; }
        if ($s['ended_reason'] !== '') {
            throw new ApiError(401, 'session_replaced', 'Another admin signed in, so this session was ended. Sign in again to continue.');
        }
        if ($s['last_seen'] < self::ago($db, (int)$cfg['session_hours'] * 3600)) {
            $db->q('DELETE FROM sessions WHERE id = ?', [$s['id']]);
            return null;
        }
        if (strtotime($db->now()) - strtotime($s['last_seen']) > 20) {
            $db->q('UPDATE sessions SET last_seen = ? WHERE id = ?', [$db->now(), $s['id']]);
        }
        return $s;
    }

    public static function logout(Db $db, ?string $token): void
    {
        if ($token) { $db->q('DELETE FROM sessions WHERE id = ?', [self::sid($token)]); }
    }

    public static function csrfOk(array $s, ?string $header): bool { return $header !== null && $header !== '' && hash_equals($s['csrf'], $header); }

    public static function changePassword(Db $db, array $s, string $current, string $new): void
    {
        $acc = $db->one('SELECT * FROM accounts WHERE id = ?', [$s['account_id']]);
        if (!$acc || !password_verify($current, $acc['password_hash'])) { throw new ApiError(400, 'bad_credentials', 'The current password is wrong.'); }
        $p = self::passwordProblem($new);
        if ($p !== '') { throw new ApiError(400, 'invalid', $p); }
        $db->q('UPDATE accounts SET password_hash = ? WHERE id = ?', [self::hash($new), $acc['id']]);
    }
}
