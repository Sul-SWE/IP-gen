<?php
/**
 * Records: preview, save, modify, trash, restore, delete forever, search.
 * Every state-changing function runs inside Db::write(), so its checks always see the newest data.
 */

declare(strict_types=1);

final class Records
{
    public const GONE = 'That record was changed or removed elsewhere, so nothing was done. The list has been refreshed.';
    public const SEARCH_FIELDS = ['all', 'name', 'gcp', 'vendor', 'engineer', 'ip'];

    /* ------------------------------------------------------------ helpers */
    /** IPs of many records at once: [record_id => [field => ip]] in worksheet order (shared text fields included). */
    public static function ipsOf(Db $db, array $records): array
    {
        $ids = array_map(fn($r) => (int)$r['id'], $records);
        $out = [];
        foreach ($records as $r) { $out[(int)$r['id']] = []; }
        if ($ids) {
            foreach (array_chunk($ids, 500) as $chunk) {
                $in = implode(',', array_fill(0, count($chunk), '?'));
                foreach ($db->all("SELECT record_id, field, ip FROM ip_assignments WHERE record_id IN ($in)", $chunk) as $a) {
                    $out[(int)$a['record_id']][$a['field']] = $a['ip'];
                }
            }
        }
        foreach ($records as $r) {
            $vals = $out[(int)$r['id']];
            foreach (jdec($r['shared_fields']) as $k => $v) { if ($v !== '' && $v !== null) { $vals[$k] = $v; } }
            $ordered = [];
            foreach (Engine::ALL_FIELDS as $f) { if (isset($vals[$f])) { $ordered[$f] = $vals[$f]; } }
            $out[(int)$r['id']] = $ordered;
        }
        return $out;
    }

    public static function serialize(array $r, array $ips): array
    {
        return [
            'id' => (int)$r['id'], 'name' => $r['name'], 'gcp' => $r['gcp_code'], 'vendor' => $r['vendor'], 'engineer' => $r['engineer_name'],
            'date' => $r['record_date'], 'status' => $r['status'], 'version' => (int)$r['version'],
            'host' => $r['host_no'] === null ? null : (int)$r['host_no'], 'block_id' => $r['block_id'] === null ? null : (int)$r['block_id'],
            'ips' => (object)$ips, 'created_at' => fmt_dt($r['created_at']), 'updated_at' => fmt_dt($r['updated_at']),
            'deleted_at' => fmt_dt($r['deleted_at']), 'deleted_by' => $r['deleted_by'], 'imported' => $r['import_batch_id'] !== null,
        ];
    }

    public static function serializeOne(Db $db, array $r): array { return self::serialize($r, self::ipsOf($db, [$r])[(int)$r['id']]); }

    /** Every name and IP in use by active and trashed records (optionally ignoring one record). */
    public static function buildIndex(Db $db, ?int $excludeId = null): array
    {
        $idx = Engine::newIndex();
        $names = [];
        foreach ($db->all('SELECT id, name, name_key, status FROM records') as $r) {
            $names[(int)$r['id']] = $r['name'];
            if ((int)$r['id'] !== $excludeId && $r['name_key'] !== null) {
                $idx['names'][strtoupper($r['name'])] = $r['status'] === 'trash' ? 'trash' : 'active';
            }
        }
        $uniq = array_flip(Engine::UNIQ);
        foreach ($db->all('SELECT record_id, field, ip FROM ip_assignments') as $a) {
            if ((int)$a['record_id'] === $excludeId) { continue; }
            if (isset($uniq[$a['field']])) { $idx['device'][$a['ip']] = $names[(int)$a['record_id']] ?? ''; }
            else { $idx['infra'][$a['ip']] = $names[(int)$a['record_id']] ?? ''; }
        }
        return $idx;
    }

    public static function addLog(Db $db, string $engineer, string $action, string $name, string $details = '', ?string $batch = null): void
    {
        $db->q('INSERT INTO audit_log (at, role, engineer_name, action, record_name, details, import_batch_id) VALUES (?, ?, ?, ?, ?, ?, ?)',
            [$db->now(), 'admin', self::cut($engineer, 40), $action, self::cut($name, 90), $details, $batch]);
    }

    public static function cut(string $s, int $n): string { return function_exists('mb_substr') ? mb_substr($s, 0, $n, 'UTF-8') : substr($s, 0, $n); }

    public static function signature(string $name, array $ips): string
    {
        ksort($ips);
        return substr(hash('sha256', jenc([$name, $ips])), 0, 32);
    }

    /** Store the IPs of a record. Device IPs carry uniq_ip, so the database itself refuses duplicates. */
    private static function setIps(Db $db, int $recordId, array $ips): void
    {
        $rows = []; $params = [];
        foreach (Engine::ipFields() as $f) {
            if (empty($ips[$f])) { continue; }
            $rows[] = '(?, ?, ?, ?)';
            array_push($params, $recordId, $f, $ips[$f], in_array($f, Engine::UNIQ, true) ? $ips[$f] : null);
        }
        if ($rows) { self::guard(fn() => $db->q('INSERT INTO ip_assignments (record_id, field, ip, uniq_ip) VALUES ' . implode(',', $rows), $params)); }
    }

    public static function sharedOf(array $ips): string
    {
        $s = [];
        foreach (Engine::SHARED_TEXT as $f) { if (!empty($ips[$f])) { $s[$f] = $ips[$f]; } }
        return jenc((object)$s);
    }

    /** The database constraints are the last line of defence. */
    public static function guard(callable $fn)
    {
        try {
            return $fn();
        } catch (PDOException $e) {
            if (Db::isDuplicate($e)) { throw ApiError::conflict('A name or IP of this record already exists. Nothing was saved; refresh and try again.'); }
            throw $e;
        }
    }

    public static function person($value, string $label): string
    {
        $name = Engine::cleanPerson($value);
        $err = Engine::checkPerson($name);
        if ($err !== '') { throw ApiError::bad("$label: $err", [], 'invalid_person'); }
        return $name;
    }

    private static function nameError(string $name, array $idx): string
    {
        $where = $idx['names'][strtoupper($name)] ?? null;
        return $where ? "The name $name already exists" . ($where === 'trash' ? ' (in the trash)' : '') . '.' : '';
    }

    private static function nameFail(string $err): ApiError
    {
        return str_contains($err, 'exists') ? ApiError::conflict($err, [], 'name_exists') : ApiError::bad($err, [], 'invalid_name');
    }

    public static function get(Db $db, int $id): array
    {
        $r = $db->one('SELECT * FROM records WHERE id = ?', [$id]);
        if (!$r) { throw ApiError::notFound(self::GONE); }
        return $r;
    }

    private static function checkVersion(array $r, $version): void
    {
        if ($version === null || (int)$r['version'] !== (int)$version) { throw ApiError::conflict(self::GONE, [], 'stale'); }
    }

    /* ------------------------------------------------------------ generation */
    /** Compute the record a save would create. Stores nothing. */
    public static function previewNew(Db $db, string $facility, string $well, string $gcp, string $vendor, string $engineer): array
    {
        $rules = Rules::load($db);
        $idx = self::buildIndex($db);
        $well = trim($well);
        if (!preg_match('/^\d{1,5}$/D', $well)) { throw ApiError::bad('Type the well number (1 to 5 digits).', [], 'invalid_name'); }
        $name = strtoupper(trim($facility)) . '-' . $well;
        $err = Engine::nameFormatError($name, $rules->activeFacilityCodes());
        if ($err === '') { $err = self::nameError($name, $idx); }
        if ($err !== '') { throw self::nameFail($err); }
        $blk = $rules->activeBlock($gcp, $vendor);
        if ($blk === null) { throw ApiError::bad('Choose a valid GCP & Ring and vendor.', [], 'invalid_range'); }
        $eng = self::person($engineer, 'TSU PAN Engineer');
        $eb = $rules->engineBlock($blk);
        $busy = Engine::busy($idx);
        $a = Engine::allocate($eb, $busy);
        $cap = (int)$eb['rule']['capacity'];
        if (!empty($a['full'])) {
            throw ApiError::conflict("$gcp / $vendor is full ($cap of $cap host numbers used). Nothing was generated. "
                . 'Choose another GCP & Ring, or ask the admin to activate the next block in Settings.', [], 'range_full');
        }
        $problems = Engine::checkIps($a['ips'], $idx);
        if ($problems) { throw ApiError::conflict('The generated addresses conflict with existing records.', $problems, 'ip_conflict'); }
        [$used] = Engine::usage($eb, $busy);
        $after = $used + 1;
        return [
            'name' => $name, 'gcp' => $gcp, 'vendor' => $vendor, 'engineer' => $eng, 'date' => $db->today(),
            'host' => $a['n'], 'capacity' => $cap, 'skipped' => $a['skipped'], 'ips' => $a['ips'], 'block_id' => $blk['id'],
            'used_after' => $after, 'warn' => $after / $cap >= $rules->warnAt, 'full_after' => $after >= $cap,
            'signature' => self::signature($name, $a['ips']),
        ];
    }

    public static function create(Db $db, array $b): array
    {
        $p = self::previewNew($db, $b['facility'], $b['well'], $b['gcp'], $b['vendor'], $b['engineer']);
        if ($p['signature'] !== $b['signature']) {
            throw ApiError::conflict('The addresses changed since your preview (another change was saved meanwhile). Check the new preview and press Save again.',
                [], 'preview_changed', ['preview' => $p]);
        }
        $now = $db->now();
        $id = self::guard(fn() => $db->insert('INSERT INTO records (name, name_key, gcp_code, vendor, block_id, host_no, engineer_name, record_date, status, shared_fields, version, created_at, updated_at, deleted_by) '
            . "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, 1, ?, ?, '')",
            [$p['name'], strtolower($p['name']), $p['gcp'], $p['vendor'], $p['block_id'], $p['host'], $p['engineer'], $p['date'], self::sharedOf($p['ips']), $now, $now]));
        self::setIps($db, $id, $p['ips']);
        self::addLog($db, $p['engineer'], 'Created', $p['name'], "{$p['gcp']} / {$p['vendor']}, host {$p['host']}, RTU IP-1 " . ($p['ips']['RTU IP-1'] ?? '-'));
        return self::get($db, $id);
    }

    /* ------------------------------------------------------------ modify */
    /** What changing GCP & Ring / vendor would do to this record's IPs. */
    public static function regenPreview(Db $db, array $r, string $gcp, string $vendor): array
    {
        if ($gcp === $r['gcp_code'] && $vendor === $r['vendor']) { return ['regen' => false]; }
        $rules = Rules::load($db);
        $blk = $rules->activeBlock($gcp, $vendor);
        if ($blk === null) {
            throw ApiError::bad("$gcp / $vendor is not configured, so new IPs cannot be generated. Keep the current GCP & Ring and vendor, or choose configured ones.", [], 'invalid_range');
        }
        $idx = self::buildIndex($db, (int)$r['id']);
        $a = Engine::allocate($rules->engineBlock($blk), Engine::busy($idx));
        if (!empty($a['full'])) { throw ApiError::conflict("$gcp / $vendor is full. Nothing can be generated there.", [], 'range_full'); }
        return ['regen' => true, 'host' => $a['n'], 'ips' => $a['ips'], 'old_ips' => (object)self::ipsOf($db, [$r])[(int)$r['id']],
            'block_id' => $blk['id'], 'signature' => self::signature($r['name'], $a['ips'])];
    }

    public static function update(Db $db, int $id, array $b): array
    {
        $r = self::get($db, $id);
        self::checkVersion($r, $b['version']);
        if ($r['status'] !== 'active') { throw ApiError::conflict('This record is in the trash. Restore it before modifying it.', [], 'stale'); }
        $who = self::person($b['actor'], 'Your name');
        $rules = Rules::load($db);
        $changes = [];

        $newName = $b['name'] === null ? $r['name'] : strtoupper(trim($b['name']));
        if ($newName !== $r['name']) {
            $allowed = $rules->activeFacilityCodes();
            $cur = Engine::splitName($r['name']);
            if ($cur) { $allowed[] = $cur[0]; }
            $err = Engine::nameFormatError($newName, $allowed);
            if ($err === '') { $err = self::nameError($newName, self::buildIndex($db, $id)); }
            if ($err !== '') { throw self::nameFail($err); }
            $changes[] = "Name {$r['name']} -> $newName";
        }

        $newEng = $b['engineer'] === null ? $r['engineer_name'] : Engine::cleanPerson($b['engineer']);
        if ($newEng !== Engine::cleanPerson($r['engineer_name'])) {
            self::person($newEng, 'Engineer on record');
            $changes[] = 'Engineer ' . ($r['engineer_name'] !== '' ? $r['engineer_name'] : '-') . " -> $newEng";
        }

        $newDate = $b['date'] === null ? $r['record_date'] : trim($b['date']);
        if ($newDate !== $r['record_date']) {
            if (!Engine::isIsoDate($newDate)) {
                throw ApiError::bad('The date must be a real date written as YYYY-MM-DD, for example ' . $db->today() . '.', [], 'invalid_date');
            }
            $changes[] = 'Date ' . ($r['record_date'] !== '' ? $r['record_date'] : '-') . " -> $newDate";
        }

        $newGcp = $b['gcp'] ?? $r['gcp_code'];
        $newVendor = $b['vendor'] ?? $r['vendor'];
        $plan = self::regenPreview($db, $r, $newGcp, $newVendor);
        if ($plan['regen']) {
            if ($plan['signature'] !== $b['signature']) {
                throw ApiError::conflict('The free addresses changed while the dialog was open. Nothing was changed; open Modify again to see the new IPs.', [], 'preview_changed');
            }
            $parts = [];
            if ($newGcp !== $r['gcp_code']) { $parts[] = 'GCP & Ring ' . ($r['gcp_code'] !== '' ? $r['gcp_code'] : '-') . " -> $newGcp"; }
            if ($newVendor !== $r['vendor']) { $parts[] = 'Vendor ' . ($r['vendor'] !== '' ? $r['vendor'] : '-') . " -> $newVendor"; }
            $parts[] = "new IPs (host {$plan['host']}, RTU IP-1 " . ($plan['ips']['RTU IP-1'] ?? '-') . ')';
            $changes[] = implode('; ', $parts);
        }
        if (!$changes) { throw ApiError::bad('Nothing was changed.', [], 'nothing_changed'); }

        $oldName = $r['name'];
        if ($plan['regen']) {
            $db->q('DELETE FROM ip_assignments WHERE record_id = ?', [$id]);   // release the old addresses before taking the new ones
            self::setIps($db, $id, $plan['ips']);
            $db->q('UPDATE records SET gcp_code = ?, vendor = ?, block_id = ?, host_no = ?, shared_fields = ? WHERE id = ?',
                [$newGcp, $newVendor, $plan['block_id'], $plan['host'], self::sharedOf($plan['ips']), $id]);
        }
        $key = $newName !== $oldName ? strtolower($newName) : $r['name_key'];
        self::guard(fn() => $db->q('UPDATE records SET name = ?, name_key = ?, engineer_name = ?, record_date = ?, version = version + 1, updated_at = ? WHERE id = ?',
            [$newName, $key, $newEng, $newDate, $db->now(), $id]));
        self::addLog($db, $who, 'Modified', $oldName . ($newName !== $oldName ? " -> $newName" : ''), implode('; ', $changes));
        return [self::get($db, $id), $plan['regen']];
    }

    /* ------------------------------------------------------------ trash, restore, delete forever */
    private static function rtuOf(Db $db, int $id): string
    {
        $v = $db->value("SELECT ip FROM ip_assignments WHERE record_id = ? AND field = 'RTU IP-1'", [$id]);
        return $v === null ? '-' : (string)$v;
    }

    public static function trash(Db $db, int $id, $version, string $actor): array
    {
        $r = self::get($db, $id);
        self::checkVersion($r, $version);
        $who = self::person($actor, 'Your name');
        if ($r['status'] === 'trash') { throw ApiError::conflict(self::GONE, [], 'stale'); }
        $now = $db->now();
        $db->q("UPDATE records SET status = 'trash', deleted_at = ?, deleted_by = ?, version = version + 1, updated_at = ? WHERE id = ?", [$now, $who, $now, $id]);
        self::addLog($db, $who, 'Deleted', $r['name'], 'Moved to trash; RTU IP-1 ' . self::rtuOf($db, $id) . ' stays reserved');
        return self::get($db, $id);
    }

    public static function restore(Db $db, int $id, $version, string $actor): array
    {
        $r = self::get($db, $id);
        self::checkVersion($r, $version);
        $who = self::person($actor, 'Your name');
        if ($r['status'] !== 'trash') { throw ApiError::conflict(self::GONE, [], 'stale'); }
        $idx = self::buildIndex($db, $id);
        $problems = [];
        if ($r['name_key'] !== null && self::nameError($r['name'], $idx) !== '') { $problems[] = self::nameError($r['name'], $idx); }
        $problems = array_merge($problems, Engine::checkIps(self::ipsOf($db, [$r])[$id], $idx));
        if ($problems) { throw ApiError::conflict("Cannot restore {$r['name']}.", $problems, 'restore_conflict'); }
        $db->q("UPDATE records SET status = 'active', deleted_at = NULL, deleted_by = '', version = version + 1, updated_at = ? WHERE id = ?", [$db->now(), $id]);
        self::addLog($db, $who, 'Restored', $r['name'], 'Back in the active list');
        return self::get($db, $id);
    }

    public static function purge(Db $db, int $id, $version, string $actor): string
    {
        $r = self::get($db, $id);
        self::checkVersion($r, $version);
        $who = self::person($actor, 'Your name');
        if ($r['status'] !== 'trash') {
            throw ApiError::conflict('Move the record to the trash first. Only records in the trash can be deleted forever.', [], 'not_in_trash');
        }
        $rtu = self::rtuOf($db, $id);
        $db->q('DELETE FROM records WHERE id = ?', [$id]);   // its IPs are removed by ON DELETE CASCADE
        self::addLog($db, $who, 'Deleted forever', $r['name'], "Name and IPs freed; RTU IP-1 was $rtu");
        return $r['name'];
    }

    /* ------------------------------------------------------------ search */
    public static function like(string $s): string
    {
        return '%' . str_replace(['!', '%', '_'], ['!!', '!%', '!_'], $s) . '%';
    }

    public static function search(Db $db, string $q = '', string $field = 'all', string $status = 'active', int $page = 1, int $size = 100, bool $newestFirst = false): array
    {
        if (!in_array($field, self::SEARCH_FIELDS, true)) { throw new ApiError(422, 'invalid', 'Unknown search field.'); }
        if (!in_array($status, ['active', 'trash', 'all'], true)) { throw new ApiError(422, 'invalid', 'Unknown status.'); }
        $where = []; $p = [];
        if ($status !== 'all') { $where[] = 'r.status = ?'; $p[] = $status; }
        $q = self::cut(trim($q), 60);
        if ($q !== '') {
            $pat = self::like(function_exists('mb_strtolower') ? mb_strtolower($q, 'UTF-8') : strtolower($q));
            $by = [
                'name' => ["LOWER(r.name) LIKE ? ESCAPE '!'", 1],
                'gcp' => ["LOWER(r.gcp_code) LIKE ? ESCAPE '!'", 1],
                'vendor' => ["LOWER(r.vendor) LIKE ? ESCAPE '!'", 1],
                'engineer' => ["LOWER(r.engineer_name) LIKE ? ESCAPE '!'", 1],
                'ip' => ["EXISTS (SELECT 1 FROM ip_assignments a WHERE a.record_id = r.id AND a.ip LIKE ? ESCAPE '!')", 1],
            ];
            if ($field === 'all') {
                $parts = array_map(fn($x) => $x[0], array_values($by));
                $parts[] = "r.record_date LIKE ? ESCAPE '!'";
                $where[] = '(' . implode(' OR ', $parts) . ')';
                for ($i = 0; $i < count($parts); $i++) { $p[] = $pat; }
            } else {
                $where[] = $by[$field][0]; $p[] = $pat;
            }
        }
        $w = $where ? 'WHERE ' . implode(' AND ', $where) : '';
        $total = (int)$db->value("SELECT COUNT(*) FROM records r $w", $p);
        $size = max(1, min($size, 500));
        $pages = max(1, intdiv($total + $size - 1, $size));
        $page = max(1, min($page, $pages));
        $order = $status === 'trash' ? 'r.deleted_at DESC, r.id DESC' : ($newestFirst ? 'r.id DESC' : 'r.id');
        $off = ($page - 1) * $size;
        $rows = $db->all("SELECT r.* FROM records r $w ORDER BY $order LIMIT $size OFFSET $off", $p);
        $ips = self::ipsOf($db, $rows);
        return ['items' => array_map(fn($r) => self::serialize($r, $ips[(int)$r['id']]), $rows), 'total' => $total, 'page' => $page, 'pages' => $pages, 'size' => $size];
    }

    public static function counts(Db $db): array
    {
        $c = ['active' => 0, 'trash' => 0];
        foreach ($db->all('SELECT status, COUNT(*) n FROM records GROUP BY status') as $r) { $c[$r['status']] = (int)$r['n']; }
        return ['active' => $c['active'], 'trash' => $c['trash'], 'log' => (int)$db->value('SELECT COUNT(*) FROM audit_log')];
    }

    public static function suggestEngineers(Db $db, string $q = '', int $limit = 12): array
    {
        $q = strtolower(Engine::cleanPerson($q));
        $names = [];
        $rows = $db->all('SELECT DISTINCT engineer_name n FROM records UNION SELECT DISTINCT engineer_name FROM audit_log');
        foreach ($rows as $r) {
            $n = Engine::cleanPerson($r['n']);
            if ($n !== '' && Engine::checkPerson($n) === '' && ($q === '' || str_contains(function_exists('mb_strtolower') ? mb_strtolower($n, 'UTF-8') : strtolower($n), $q))) {
                $names[$n] = true;
            }
        }
        $names = array_keys($names);
        usort($names, fn($a, $b) => strcasecmp($a, $b));
        return array_slice($names, 0, $limit);
    }
}
