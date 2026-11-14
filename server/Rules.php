<?php
/** Rules stored in the database: facilities, GCP & Rings, vendors and address blocks. */

declare(strict_types=1);

final class Rules
{
    public array $facilities = [];  // rows: id, code, active
    public array $gcps = [];        // rows: id, code, octet1, octet2, rtu_vlan, plc_vlan, active
    public array $vendors = [];     // rows: id, name, capacity, octets (array), fields (array), active
    public array $blocks = [];      // rows: id, gcp_id, vendor_id, seq, status, octets (array), created_at, activated_at, gcp (row), vendor (row)
    public string $mask = '255.255.255.0';
    public float $warnAt = 0.9;

    public static function load(Db $db): self
    {
        $r = new self();
        foreach ($db->all('SELECT id, code, active FROM facilities ORDER BY id') as $f) {
            $r->facilities[] = ['id' => (int)$f['id'], 'code' => $f['code'], 'active' => (bool)$f['active']];
        }
        $gById = [];
        foreach ($db->all('SELECT * FROM gcp_rings ORDER BY id') as $g) {
            $g = ['id' => (int)$g['id'], 'code' => $g['code'], 'octet1' => (int)$g['octet1'], 'octet2' => (int)$g['octet2'],
                  'rtu_vlan' => $g['rtu_vlan'], 'plc_vlan' => $g['plc_vlan'], 'active' => (bool)$g['active']];
            $r->gcps[] = $g; $gById[$g['id']] = $g;
        }
        $vById = [];
        foreach ($db->all('SELECT * FROM vendors ORDER BY id') as $v) {
            $v = ['id' => (int)$v['id'], 'name' => $v['name'], 'capacity' => (int)$v['capacity'], 'octets' => jdec($v['octets']),
                  'fields' => jdec($v['fields']), 'active' => (bool)$v['active']];
            $r->vendors[] = $v; $vById[$v['id']] = $v;
        }
        foreach ($db->all('SELECT * FROM blocks ORDER BY gcp_id, vendor_id, seq') as $b) {
            $r->blocks[] = ['id' => (int)$b['id'], 'gcp_id' => (int)$b['gcp_id'], 'vendor_id' => (int)$b['vendor_id'], 'seq' => (int)$b['seq'],
                'status' => $b['status'], 'octets' => jdec($b['octets']), 'created_at' => $b['created_at'], 'activated_at' => $b['activated_at'],
                'gcp' => $gById[(int)$b['gcp_id']], 'vendor' => $vById[(int)$b['vendor_id']]];
        }
        $r->mask = self::getSetting($db, 'subnet_mask', '255.255.255.0');
        $w = self::getSetting($db, 'warn_at', '0.9');
        $r->warnAt = is_numeric($w) ? (float)$w : 0.9;
        return $r;
    }

    public function facilityCodes(): array { return array_map(fn($f) => $f['code'], $this->facilities); }
    public function activeFacilityCodes(): array { return array_values(array_map(fn($f) => $f['code'], array_filter($this->facilities, fn($f) => $f['active']))); }

    public function activeBlock(string $gcp, string $vendor): ?array
    {
        foreach ($this->blocks as $b) {
            if ($b['status'] === 'active' && $b['gcp']['code'] === $gcp && $b['vendor']['name'] === $vendor && $b['gcp']['active'] && $b['vendor']['active']) {
                return $b;
            }
        }
        return null;
    }

    public static function vendorRule(array $v): array
    {
        return ['name' => $v['name'], 'capacity' => (int)$v['capacity'],
            'fields' => array_map(fn($f) => ['field' => (string)$f['field'], 'net' => (string)$f['net'], 'a' => (int)$f['a'], 'b' => (int)$f['b']], $v['fields'])];
    }

    public function engineBlock(array $b): array
    {
        $g = $b['gcp'];
        return ['gcp' => $g['code'], 'octet1' => $g['octet1'], 'octet2' => $g['octet2'], 'octets' => array_map('intval', $b['octets']),
            'rule' => self::vendorRule($b['vendor']), 'rtu_vlan' => $g['rtu_vlan'], 'plc_vlan' => $g['plc_vlan'], 'mask' => $this->mask, 'block_id' => $b['id']];
    }

    public function engineBlocks(): array { return array_map(fn($b) => $this->engineBlock($b), $this->blocks); }

    public function importConfig(): array
    {
        $gcps = [];
        foreach ($this->gcps as $g) { $gcps[$g['code']] = [$g['rtu_vlan'], $g['plc_vlan']]; }
        return ['facilities' => $this->facilityCodes(), 'blocks' => $this->engineBlocks(), 'gcps' => $gcps,
            'vendors' => array_map(fn($v) => $v['name'], $this->vendors), 'mask' => $this->mask];
    }

    /* ------------------------------------------------------------ settings */
    public static function getSetting(Db $db, string $name, string $default = ''): string
    {
        $v = $db->value('SELECT value FROM settings WHERE name = ?', [$name]);
        return $v === null ? $default : (string)$v;
    }

    public static function setSetting(Db $db, string $name, string $value): void
    {
        $db->q('INSERT INTO settings (name, value) VALUES (?, ?) ON DUPLICATE KEY UPDATE value = VALUES(value)', [$name, $value]);
    }

    /* ------------------------------------------------------------ seeding (first setup only) */
    public static function seedDefaults(Db $db): bool
    {
        $d = require __DIR__ . '/defaults.php';
        $db->q("INSERT IGNORE INTO settings (name, value) VALUES ('write_lock', '1')");
        foreach ($d['settings'] as $k => $v) { $db->q('INSERT IGNORE INTO settings (name, value) VALUES (?, ?)', [$k, $v]); }
        if ($db->value('SELECT id FROM gcp_rings LIMIT 1') !== null || $db->value('SELECT id FROM vendors LIMIT 1') !== null) { return false; }
        foreach ($d['facilities'] as $code) { $db->q('INSERT INTO facilities (code, active) VALUES (?, 1)', [$code]); }
        $vendors = [];
        foreach ($d['vendors'] as $v) {
            $id = $db->insert('INSERT INTO vendors (name, capacity, octets, fields, active) VALUES (?, ?, ?, ?, 1)', [$v['name'], $v['capacity'], jenc($v['octets']), jenc($v['fields'])]);
            $vendors[] = ['id' => $id] + $v + ['active' => true];
        }
        foreach ($d['gcp_rings'] as [$code, $o1, $o2, $rv, $pv]) {
            $gid = $db->insert('INSERT INTO gcp_rings (code, octet1, octet2, rtu_vlan, plc_vlan, active) VALUES (?, ?, ?, ?, ?, 1)', [$code, $o1, $o2, $rv, $pv]);
            $g = ['id' => $gid, 'code' => $code, 'octet1' => $o1, 'octet2' => $o2, 'rtu_vlan' => $rv, 'plc_vlan' => $pv, 'active' => true];
            foreach ($vendors as $v) { self::createBlock($db, $g, $v, $v['octets'], 'active'); }
        }
        return true;
    }

    /* ------------------------------------------------------------ blocks */
    private static function usedOctets(array $v, array $octets): array
    {
        $nets = array_values(array_unique(array_map(fn($f) => (string)$f['net'], $v['fields'])));
        sort($nets);
        $out = [];
        foreach ($nets as $n) {
            if (!array_key_exists($n, $octets) || !is_numeric($octets[$n]) || (int)$octets[$n] != $octets[$n]) {
                throw ApiError::bad("Give a third octet (0 to 255) for each network of {$v['name']}: " . implode(', ', $nets) . '.');
            }
            $out[$n] = (int)$octets[$n];
        }
        return $out;
    }

    private static function rowGcp(Db $db, int $id): ?array
    {
        $g = $db->one('SELECT * FROM gcp_rings WHERE id = ?', [$id]);
        return $g ? ['id' => (int)$g['id'], 'code' => $g['code'], 'octet1' => (int)$g['octet1'], 'octet2' => (int)$g['octet2'],
            'rtu_vlan' => $g['rtu_vlan'], 'plc_vlan' => $g['plc_vlan'], 'active' => (bool)$g['active']] : null;
    }

    private static function rowVendor(Db $db, int $id): ?array
    {
        $v = $db->one('SELECT * FROM vendors WHERE id = ?', [$id]);
        return $v ? ['id' => (int)$v['id'], 'name' => $v['name'], 'capacity' => (int)$v['capacity'], 'octets' => jdec($v['octets']),
            'fields' => jdec($v['fields']), 'active' => (bool)$v['active']] : null;
    }

    public static function rowBlock(Db $db, int $id): ?array
    {
        $b = $db->one('SELECT * FROM blocks WHERE id = ?', [$id]);
        if (!$b) { return null; }
        return ['id' => (int)$b['id'], 'gcp_id' => (int)$b['gcp_id'], 'vendor_id' => (int)$b['vendor_id'], 'seq' => (int)$b['seq'], 'status' => $b['status'],
            'octets' => jdec($b['octets']), 'created_at' => $b['created_at'], 'activated_at' => $b['activated_at'],
            'gcp' => self::rowGcp($db, (int)$b['gcp_id']), 'vendor' => self::rowVendor($db, (int)$b['vendor_id'])];
    }

    private static function createBlock(Db $db, array $g, array $v, array $octets, string $status): array
    {
        $octs = self::usedOctets($v, $octets);
        $errors = Engine::validateRule(self::vendorRule($v), $octs);
        if ($errors) { throw ApiError::bad("The block for {$g['code']} / {$v['name']} is not valid.", $errors); }
        $taken = [];
        foreach ($db->all('SELECT octet3 FROM block_octets WHERE gcp_id = ?', [$g['id']]) as $o) { $taken[(int)$o['octet3']] = true; }
        $clash = [];
        foreach ($octs as $o) { if (isset($taken[$o])) { $clash[] = $o; } }
        sort($clash);
        if ($clash) {
            throw ApiError::conflict("In {$g['code']}, third octet " . implode(', ', $clash) . ' already belongs to another block. Choose octets that are not used in this GCP & Ring.');
        }
        $seq = 1 + (int)$db->value('SELECT COALESCE(MAX(seq), 0) FROM blocks WHERE gcp_id = ? AND vendor_id = ?', [$g['id'], $v['id']]);
        $now = $db->now();
        $id = $db->insert('INSERT INTO blocks (gcp_id, vendor_id, seq, status, octets, created_at, activated_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
            [$g['id'], $v['id'], $seq, $status, jenc($octs), $now, $status === 'active' ? $now : null]);
        foreach ($octs as $o) { $db->q('INSERT INTO block_octets (gcp_id, octet3, block_id) VALUES (?, ?, ?)', [$g['id'], $o, $id]); }
        return self::rowBlock($db, $id);
    }

    public static function addPlannedBlock(Db $db, int $gcpId, int $vendorId, array $octets): array
    {
        $g = self::rowGcp($db, $gcpId); $v = self::rowVendor($db, $vendorId);
        if (!$g || !$v) { throw ApiError::notFound('GCP & Ring or vendor not found.'); }
        $existing = $db->all('SELECT status FROM blocks WHERE gcp_id = ? AND vendor_id = ?', [$gcpId, $vendorId]);
        $st = array_map(fn($b) => $b['status'], $existing);
        if (in_array('planned', $st, true)) { throw ApiError::conflict("{$g['code']} / {$v['name']} already has a planned block. Activate or remove it first."); }
        return self::createBlock($db, $g, $v, $octets, in_array('active', $st, true) ? 'planned' : 'active');
    }

    public static function activateBlock(Db $db, int $blockId): array
    {
        $b = self::rowBlock($db, $blockId);
        if (!$b) { throw ApiError::notFound('Block not found.'); }
        if ($b['status'] !== 'planned') { throw ApiError::conflict('Only a planned block can be activated.'); }
        $old = $db->one("SELECT id, seq FROM blocks WHERE gcp_id = ? AND vendor_id = ? AND status = 'active'", [$b['gcp_id'], $b['vendor_id']]);
        if ($old) { $db->q("UPDATE blocks SET status = 'retired' WHERE id = ?", [$old['id']]); }
        $db->q("UPDATE blocks SET status = 'active', activated_at = ? WHERE id = ?", [$db->now(), $blockId]);
        return [self::rowBlock($db, $blockId), $old ? ['seq' => (int)$old['seq']] : null];
    }

    public static function removePlannedBlock(Db $db, int $blockId): array
    {
        $b = self::rowBlock($db, $blockId);
        if (!$b) { throw ApiError::notFound('Block not found.'); }
        if ($b['status'] !== 'planned') { throw ApiError::conflict('Only a planned block can be removed. Active and retired blocks keep their addresses reserved.'); }
        $db->q('DELETE FROM blocks WHERE id = ?', [$blockId]);
        return $b;
    }

    /* ------------------------------------------------------------ GCP & Ring, vendors, facilities */
    private static function vlan($value, string $label): string
    {
        $s = trim((string)$value);
        if (!preg_match('/^\d{1,4}$/D', $s) || (int)$s < 1 || (int)$s > 4094) { throw ApiError::bad("$label must be a number from 1 to 4094."); }
        return (string)(int)$s;
    }

    public static function addGcp(Db $db, string $code, int $o1, int $o2, $rv, $pv): array
    {
        $code = strtoupper(trim($code));
        if (!preg_match('/^[A-Z0-9][A-Z0-9_\-]{1,39}$/D', $code)) {
            throw ApiError::bad('The GCP & Ring code must be 2 to 40 characters: capital letters, digits, dash or underscore (for example HDGCP2-R1).');
        }
        if (!($o1 >= 1 && $o1 <= 223 && $o1 !== 127 && $o2 >= 0 && $o2 <= 255)) { throw ApiError::bad('Octet 1 must be 1 to 223 (not 127) and octet 2 must be 0 to 255.'); }
        if ($db->value('SELECT id FROM gcp_rings WHERE code = ?', [$code]) !== null) { throw ApiError::conflict("The GCP & Ring $code already exists."); }
        $other = $db->value('SELECT code FROM gcp_rings WHERE octet1 = ? AND octet2 = ?', [$o1, $o2]);
        if ($other !== null) { throw ApiError::conflict("$o1.$o2.x.x is already used by $other. Two GCP & Rings cannot share the same first two octets."); }
        $rv = self::vlan($rv, 'RTU VLAN'); $pv = self::vlan($pv, 'PLC VLAN');
        $id = $db->insert('INSERT INTO gcp_rings (code, octet1, octet2, rtu_vlan, plc_vlan, active) VALUES (?, ?, ?, ?, ?, 1)', [$code, $o1, $o2, $rv, $pv]);
        $g = self::rowGcp($db, $id);
        foreach ($db->all('SELECT id FROM vendors WHERE active = 1 ORDER BY id') as $v) {
            $vr = self::rowVendor($db, (int)$v['id']);
            self::createBlock($db, $g, $vr, $vr['octets'], 'active');
        }
        return $g;
    }

    public static function updateGcp(Db $db, int $id, $rv, $pv, ?bool $active): array
    {
        $g = self::rowGcp($db, $id);
        if (!$g) { throw ApiError::notFound('GCP & Ring not found.'); }
        if ($rv !== null) { $db->q('UPDATE gcp_rings SET rtu_vlan = ? WHERE id = ?', [self::vlan($rv, 'RTU VLAN'), $id]); }
        if ($pv !== null) { $db->q('UPDATE gcp_rings SET plc_vlan = ? WHERE id = ?', [self::vlan($pv, 'PLC VLAN'), $id]); }
        if ($active !== null) { $db->q('UPDATE gcp_rings SET active = ? WHERE id = ?', [$active ? 1 : 0, $id]); }
        return self::rowGcp($db, $id);
    }

    /** Checks a vendor definition. Returns [rule, octets of the networks it uses]. */
    public static function parseVendor(string $name, int $capacity, array $octets, array $fields): array
    {
        $name = Engine::cleanPerson($name);
        if (!preg_match('/^[A-Za-z][A-Za-z0-9 _\-]{1,29}$/D', $name)) {
            throw ApiError::bad('The vendor name must be 2 to 30 characters: letters, digits, spaces, dash or underscore, starting with a letter.');
        }
        $frs = [];
        foreach ($fields as $f) {
            $frs[] = ['field' => (string)$f['field'], 'net' => strtoupper((string)$f['net']), 'a' => (int)$f['a'], 'b' => (int)$f['b']];
        }
        $octs = [];
        foreach ($octets as $k => $v) { $octs[strtoupper((string)$k)] = (int)$v; }
        $rule = ['name' => $name, 'capacity' => $capacity, 'fields' => $frs];
        $used = array_unique(array_map(fn($f) => $f['net'], $frs));
        $mine = array_filter($octs, fn($k) => in_array($k, $used, true), ARRAY_FILTER_USE_KEY);
        $errors = Engine::validateRule($rule, $mine);
        if ($errors) { throw ApiError::bad('This vendor rule is not safe.', $errors); }
        return [$rule, $mine];
    }

    public static function addVendor(Db $db, string $name, int $capacity, array $octets, array $fields): array
    {
        [$rule, $octs] = self::parseVendor($name, $capacity, $octets, $fields);
        if ($db->value('SELECT id FROM vendors WHERE name = ?', [$rule['name']]) !== null) { throw ApiError::conflict("The vendor {$rule['name']} already exists."); }
        $id = $db->insert('INSERT INTO vendors (name, capacity, octets, fields, active) VALUES (?, ?, ?, ?, 1)', [$rule['name'], $rule['capacity'], jenc($octs), jenc($rule['fields'])]);
        $v = self::rowVendor($db, $id);
        foreach ($db->all('SELECT id FROM gcp_rings WHERE active = 1 ORDER BY id') as $g) {
            self::createBlock($db, self::rowGcp($db, (int)$g['id']), $v, $octs, 'active');
        }
        return $v;
    }

    public static function setVendorActive(Db $db, int $id, bool $active): array
    {
        $v = self::rowVendor($db, $id);
        if (!$v) { throw ApiError::notFound('Vendor not found.'); }
        $db->q('UPDATE vendors SET active = ? WHERE id = ?', [$active ? 1 : 0, $id]);
        return self::rowVendor($db, $id);
    }

    public static function addFacility(Db $db, string $code): array
    {
        $code = strtoupper(trim($code));
        if (!preg_match(Engine::FACILITY_CODE_RE, $code)) {
            throw ApiError::bad('A facility code must be 2 to 8 characters: capital letters or digits, starting with a letter (for example UTMN).');
        }
        if ($db->value('SELECT id FROM facilities WHERE code = ?', [$code]) !== null) { throw ApiError::conflict("The facility $code already exists."); }
        $id = $db->insert('INSERT INTO facilities (code, active) VALUES (?, 1)', [$code]);
        return ['id' => $id, 'code' => $code];
    }

    public static function setFacilityActive(Db $db, int $id, bool $active): array
    {
        $f = $db->one('SELECT id, code FROM facilities WHERE id = ?', [$id]);
        if (!$f) { throw ApiError::notFound('Facility not found.'); }
        $db->q('UPDATE facilities SET active = ? WHERE id = ?', [$active ? 1 : 0, $id]);
        return ['id' => (int)$f['id'], 'code' => $f['code'], 'active' => $active];
    }
}
