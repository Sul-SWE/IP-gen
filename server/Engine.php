<?php
/**
 * Rule engine: address generation, allocation and validation.
 * Pure code: no web, no database. Everything it needs is passed in.
 * Messages are plain text (the browser escapes them).
 */

declare(strict_types=1);

final class Engine
{
    /** IPs that must never repeat across records (active or in the trash). */
    public const UNIQ = ['RTU IP-1', 'RTU IP-2', 'PLC IP-1', 'PLC IP-2', 'RTU Internal IP-1', 'RTU Internal IP-2', 'RTU-HMI IP', 'IES Moxa IP'];
    /** Infrastructure addresses: shared by design, never given to a device. */
    public const INFRA = ['Engg. Laptop IP', 'Gateway-1', 'Gateway-2'];
    public const SHARED_TEXT = ['Subnet Mask', 'RTU VLAN', 'PLC VLAN'];
    /** Worksheet / Excel order. */
    public const ALL_FIELDS = ['RTU IP-1', 'RTU IP-2', 'PLC IP-1', 'PLC IP-2', 'RTU Internal IP-1', 'RTU Internal IP-2',
        'RTU-HMI IP', 'Engg. Laptop IP', 'IES Moxa IP', 'Gateway-1', 'Gateway-2', 'Subnet Mask', 'RTU VLAN', 'PLC VLAN'];
    public const FIXED_COLUMNS = ['Facility Name', 'GCP & Ring', 'Vendor', 'Date', 'TSU PAN Engineer'];
    public const NETS = ['A', 'B', 'M']; // network slots a vendor rule may use (M = Moxa network)
    public const FACILITY_CODE_RE = '/^[A-Z][A-Z0-9]{1,7}$/';

    public static function ipFields(): array { return array_merge(self::UNIQ, self::INFRA); }
    public static function columns(): array { return array_merge(self::FIXED_COLUMNS, self::ALL_FIELDS); }

    /* ------------------------------------------------------------ rules
       A vendor rule: ['name' => .., 'capacity' => int, 'fields' => [['field','net','a','b'], ...]]
       A block: ['gcp','octet1','octet2','octets' => [net => octet3], 'rule' => vendor rule,
                 'rtu_vlan','plc_vlan','mask','block_id'] */

    /** All addresses of host number n in this block, in worksheet order. */
    public static function build(array $block, int $n): array
    {
        $p = $block['octet1'] . '.' . $block['octet2'] . '.';
        $byField = [];
        foreach ($block['rule']['fields'] as $f) {
            $byField[$f['field']] = $f;
        }
        $out = [];
        foreach (self::ALL_FIELDS as $name) {
            if (isset($byField[$name])) {
                $f = $byField[$name];
                $out[$name] = $p . $block['octets'][$f['net']] . '.' . ((int)$f['a'] * $n + (int)$f['b']);
            }
        }
        $out['Subnet Mask'] = $block['mask'] ?? '255.255.255.0';
        if (($block['rtu_vlan'] ?? '') !== '') { $out['RTU VLAN'] = (string)$block['rtu_vlan']; }
        if (($block['plc_vlan'] ?? '') !== '') { $out['PLC VLAN'] = (string)$block['plc_vlan']; }
        $ordered = [];
        foreach (self::ALL_FIELDS as $k) {
            if (array_key_exists($k, $out)) { $ordered[$k] = $out[$k]; }
        }
        return $ordered;
    }

    /** Problems that would make a vendor rule unsafe. Empty array = safe for every host number. */
    public static function validateRule(array $rule, ?array $octets = null): array
    {
        $errors = [];
        $cap = (int)$rule['capacity'];
        if ($cap < 1 || $cap > 254) {
            return ['Capacity must be between 1 and 254.'];
        }
        $names = array_map(fn($f) => $f['field'], $rule['fields']);
        if (count(array_unique($names)) !== count($names)) { $errors[] = 'A field is listed twice.'; }
        foreach ($rule['fields'] as $f) {
            if (!in_array($f['field'], self::ipFields(), true)) { $errors[] = $f['field'] . ' is not an IP field.'; }
            if (!in_array($f['net'], self::NETS, true)) { $errors[] = $f['field'] . ': network must be one of ' . implode(', ', self::NETS) . '.'; }
            if (in_array($f['field'], self::INFRA, true) && (int)$f['a'] !== 0) { $errors[] = $f['field'] . ' is shared by all records, so its host must be a fixed number.'; }
            if (in_array($f['field'], self::UNIQ, true) && (int)$f['a'] < 1) { $errors[] = $f['field'] . ' must change with the host number (multiplier of n must be 1 or more).'; }
        }
        if (!in_array('RTU IP-1', $names, true)) { $errors[] = 'The rule must define RTU IP-1.'; }
        if ($errors) { return $errors; }

        $usedNets = array_values(array_unique(array_map(fn($f) => $f['net'], $rule['fields'])));
        if ($octets !== null) {
            $missing = array_values(array_diff($usedNets, array_keys($octets)));
            sort($missing);
            if ($missing) { $errors[] = 'Third octet missing for network ' . implode(', ', $missing) . '.'; }
            $vals = [];
            foreach ($usedNets as $k) { if (array_key_exists($k, $octets)) { $vals[] = (int)$octets[$k]; } }
            foreach ($vals as $v) { if ($v < 0 || $v > 255) { $errors[] = 'Third octets must be between 0 and 255.'; break; } }
            if (count(array_unique($vals)) !== count($vals)) { $errors[] = 'Each network of a block needs its own third octet.'; }
        }
        $infra = [];
        foreach ($rule['fields'] as $f) {
            if (in_array($f['field'], self::INFRA, true)) { $infra[$f['net'] . '|' . (int)$f['b']] = $f['field']; }
        }
        foreach ($rule['fields'] as $f) {
            if (in_array($f['field'], self::INFRA, true) && ((int)$f['b'] < 1 || (int)$f['b'] > 254)) {
                $errors[] = $f['field'] . ': host ' . (int)$f['b'] . ' is outside 1 to 254.';
            }
        }
        $seen = [];
        for ($n = 1; $n <= $cap; $n++) {
            foreach ($rule['fields'] as $f) {
                if (!in_array($f['field'], self::UNIQ, true)) { continue; }
                $h = (int)$f['a'] * $n + (int)$f['b'];
                if ($h < 1 || $h > 254) {
                    $errors[] = "{$f['field']}: host number $n gives .$h, outside 1 to 254.";
                    return $errors;
                }
                $key = $f['net'] . '|' . $h;
                if (isset($infra[$key])) {
                    $errors[] = "{$f['field']}: host number $n gives .$h, which is {$infra[$key]}.";
                    return $errors;
                }
                if (isset($seen[$key])) {
                    $errors[] = "{$f['field']}: host number $n gives .$h on network {$f['net']}, already used by {$seen[$key]}.";
                    return $errors;
                }
                $seen[$key] = "{$f['field']} (host number $n)";
            }
        }
        return $errors;
    }

    /* ------------------------------------------------------------ IPv4 helpers */
    /** '018.1.20.07' -> '18.1.20.7'; anything that is not dotted IPv4 -> null. */
    public static function canonIp($value): ?string
    {
        if ($value === null || is_array($value)) { return null; }
        if (!preg_match('/^\s*(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\s*$/D', (string)$value, $m)) { return null; }
        $o = array_map('intval', array_slice($m, 1));
        foreach ($o as $x) { if ($x > 255) { return null; } }
        return implode('.', $o);
    }

    public static function ipInt(string $ip): int
    {
        $p = array_map('intval', explode('.', $ip));
        return ($p[0] << 24) | ($p[1] << 16) | ($p[2] << 8) | $p[3];
    }

    /** Prefix length of a subnet mask, or -1 when it is not a valid mask. */
    public static function maskBits($mask): int
    {
        $c = self::canonIp($mask);
        if ($c === null) { return -1; }
        $bits = str_pad(decbin(self::ipInt($c)), 32, '0', STR_PAD_LEFT);
        return preg_match('/^1+0*$/', $bits) ? substr_count($bits, '1') : -1;
    }

    /** 'network' / 'broadcast' when ip is the first or last address of its subnet, else ''. */
    public static function edgeAddress(string $ip, string $mask): string
    {
        $b = self::maskBits($mask);
        if ($b < 1 || $b > 30) { return ''; }
        $size = 1 << (32 - $b);
        $host = self::ipInt($ip) % $size;
        return $host === 0 ? 'network' : ($host === $size - 1 ? 'broadcast' : '');
    }

    public static function sameSubnet(string $a, string $b, string $mask): bool
    {
        $bits = self::maskBits($mask);
        if ($bits < 1) { return true; }
        return (self::ipInt($a) >> (32 - $bits)) === (self::ipInt($b) >> (32 - $bits));
    }

    public static function ipKey(string $ip): string { return self::canonIp($ip) ?? $ip; }

    /* ------------------------------------------------------------ allocation */
    public static function isBusy(array $ips, array $busy): bool
    {
        foreach (self::UNIQ as $f) {
            if (!empty($ips[$f]) && isset($busy[$ips[$f]])) { return true; }
        }
        return false;
    }

    /** First free host number. `busy` holds every device and infrastructure IP in use (ip => name).
     *  Returns ['n','ips','skipped'] or ['full' => true, 'skipped' => [...]]. */
    public static function allocate(array $block, array $busy): array
    {
        $skipped = [];
        $cap = (int)$block['rule']['capacity'];
        for ($n = 1; $n <= $cap; $n++) {
            $ips = self::build($block, $n);
            if (!self::isBusy($ips, $busy)) { return ['n' => $n, 'ips' => $ips, 'skipped' => $skipped]; }
            $skipped[] = $n;
        }
        return ['full' => true, 'skipped' => $skipped];
    }

    /** [used, max, next free host number or 0]. */
    public static function usage(array $block, array $busy): array
    {
        $cap = (int)$block['rule']['capacity'];
        $free = 0; $next = 0;
        for ($n = 1; $n <= $cap; $n++) {
            if (!self::isBusy(self::build($block, $n), $busy)) { $free++; if (!$next) { $next = $n; } }
        }
        return [$cap - $free, $cap, $next];
    }

    /** Host number n when the device IPs follow this block's rule exactly, else 0. */
    public static function ruleHost(array $block, array $ips): int
    {
        $cap = (int)$block['rule']['capacity'];
        for ($n = 1; $n <= $cap; $n++) {
            $b = self::build($block, $n);
            $ok = true;
            foreach (self::UNIQ as $f) {
                $want = $b[$f] ?? '';
                $have = !empty($ips[$f]) ? self::ipKey((string)$ips[$f]) : '';
                if ($want !== $have) { $ok = false; break; }
            }
            if ($ok) { return $n; }
        }
        return 0;
    }

    /* ------------------------------------------------------------ names, people, dates */
    public static function splitName(string $name): ?array
    {
        if (preg_match('/^([A-Z][A-Z0-9]{1,7})-(\d{1,5})$/D', strtoupper(trim($name)), $m)) { return [$m[1], $m[2]]; }
        return null;
    }

    public static function isStdName(string $name): bool { return self::splitName($name) !== null; }

    public static function nameFormatError(string $name, array $facilities): string
    {
        $p = self::splitName($name);
        if ($p === null || !in_array($p[0], $facilities, true)) {
            return 'Name must look like UTMN-1000: a facility from the list, a dash, then the well number (1 to 5 digits).';
        }
        return '';
    }

    public static function isPlaceholder(string $name): bool
    {
        return in_array(strtoupper(trim($name)), ['USED', 'UNKNOWN', '-', ''], true);
    }

    public static function len(string $s): int
    {
        return function_exists('mb_strlen') ? mb_strlen($s, 'UTF-8') : (int)preg_match_all('/./us', $s);
    }

    public static function cleanPerson($value): string
    {
        $s = $value === null ? '' : (string)$value;
        $s = preg_replace('/\s+/u', ' ', $s) ?? $s;
        return trim($s);
    }

    public static function checkPerson($value): string
    {
        $s = self::cleanPerson($value);
        $n = self::len($s);
        if ($n < 2 || $n > 40) { return 'Type your name (2 to 40 characters).'; }
        if (!preg_match("/^\\p{L}(?:\\p{L}|\\p{M}|[ .'\\-])*$/uD", $s)) {
            return 'A name may only contain letters, spaces, dots, dashes and apostrophes.';
        }
        return '';
    }

    public static function isIsoDate($s): bool
    {
        if (!is_string($s) || !preg_match('/^(\d{4})-(\d{2})-(\d{2})$/D', $s, $m)) { return false; }
        return checkdate((int)$m[2], (int)$m[3], (int)$m[1]) && (int)$m[1] >= 1;
    }

    /** Excel serial dates -> YYYY-MM-DD; other values kept as text (max 20 chars). */
    public static function importDate($v): string
    {
        if ((is_int($v) || is_float($v)) && $v > 20000 && $v < 80000) {
            $days = (int)round($v);
            return gmdate('Y-m-d', ($days - 25569) * 86400);
        }
        if ($v === null || $v === false) { return ''; }
        if ($v === true) { return 'True'; }
        $s = trim(self::text($v));
        return function_exists('mb_substr') ? mb_substr($s, 0, 20, 'UTF-8') : substr($s, 0, 20);
    }

    /** Cell value as text (like Python str(): whole floats without .0). */
    public static function text($v): string
    {
        if ($v === null) { return ''; }
        if (is_bool($v)) { return $v ? 'True' : 'False'; }
        if (is_float($v) && floor($v) === $v && abs($v) < 1e15) { return (string)(int)$v; }
        if (is_float($v)) { return (string)$v; }
        return (string)$v;
    }

    /* ------------------------------------------------------------ conflicts
       An index: ['names' => [UPPER => 'active'|'trash'|'file'], 'device' => [ip => name], 'infra' => [ip => name]] */
    public static function newIndex(): array { return ['names' => [], 'device' => [], 'infra' => []]; }

    public static function indexAdd(array &$idx, string $name, array $ips, string $where = 'file'): void
    {
        if (!self::isPlaceholder($name)) { $idx['names'][strtoupper($name)] = $where; }
        foreach (self::UNIQ as $f) { if (!empty($ips[$f])) { $idx['device'][self::ipKey((string)$ips[$f])] = $name; } }
        foreach (self::INFRA as $f) { if (!empty($ips[$f])) { $idx['infra'][self::ipKey((string)$ips[$f])] = $name; } }
    }

    public static function busy(array $idx): array { return $idx['device'] + $idx['infra']; }

    /** Conflicts of a record's device IPs with the index and with each other. */
    public static function checkIps(array $ips, array $idx): array
    {
        $errors = []; $seen = [];
        foreach (self::UNIQ as $f) {
            if (empty($ips[$f])) { continue; }
            $k = self::ipKey((string)$ips[$f]);
            if (isset($seen[$k])) { $errors[] = "$f $k repeats {$seen[$k]} of the same record"; }
            elseif (isset($idx['device'][$k])) { $errors[] = "$f $k is already used by {$idx['device'][$k]}"; }
            elseif (isset($idx['infra'][$k])) { $errors[] = "$f $k is a gateway or laptop address of {$idx['infra'][$k]}"; }
            $seen[$k] = $f;
        }
        return $errors;
    }

    /* ------------------------------------------------------------ import
       $cfg: ['facilities' => [codes], 'blocks' => [blocks], 'gcps' => [code => [rtu, plc]], 'vendors' => [names], 'mask' => '...']
       Returns ['line','name','record' => array|null,'errors','warnings']. Does not modify $idx. */
    public static function checkImportRow(array $row, array $idx, array $cfg, int $line = 0): array
    {
        $errors = []; $warnings = [];
        $val = function (string $k) use ($row): string { return trim(self::text($row[$k] ?? null)); };
        $up = fn(string $s) => function_exists('mb_strtoupper') ? mb_strtoupper($s, 'UTF-8') : strtoupper($s);

        $name = $up($val('Facility Name'));
        $placeholder = self::isPlaceholder($name);
        if (self::len($name) > 40) {
            $errors[] = 'Facility Name is longer than 40 characters';
        } elseif (!$placeholder) {
            if (self::nameFormatError($name, $cfg['facilities']) !== '') {
                $errors[] = "Facility Name \"$name\" must look like UTMN-1000 (a facility from the list, a dash, 1 to 5 digits)";
            } elseif (isset($idx['names'][$name])) {
                $where = ['trash' => ' (in the trash)', 'file' => ' (earlier row in this file)'][$idx['names'][$name]] ?? '';
                $errors[] = "the name $name already exists$where";
            }
        }

        $gcp = $val('GCP & Ring'); $vendor = $val('Vendor'); $eng = self::cleanPerson(self::text($row['TSU PAN Engineer'] ?? null));
        if (self::len($gcp) > 40) { $errors[] = 'GCP & Ring is longer than 40 characters'; }
        if (self::len($vendor) > 30) { $errors[] = 'Vendor is longer than 30 characters'; }
        if (self::len($eng) > 40) { $errors[] = 'TSU PAN Engineer is longer than 40 characters'; }
        foreach (array_keys($cfg['gcps']) as $g) { if (strtolower((string)$g) === strtolower($gcp)) { $gcp = (string)$g; break; } }
        foreach ($cfg['vendors'] as $v) { if (strtolower($v) === strtolower($vendor)) { $vendor = $v; break; } }

        $ips = [];
        foreach (self::ALL_FIELDS as $f) {
            $s = $val($f);
            if ($s === '') { continue; }
            if (self::len($s) > 30) { $errors[] = "$f is longer than 30 characters"; continue; }
            if (in_array($f, self::ipFields(), true)) {
                $c = self::canonIp($s);
                if ($c === null) { $errors[] = "$f \"$s\" is not a valid IPv4 address (4 numbers from 0 to 255)"; continue; }
                if ($c !== $s) { $warnings[] = "$f $s was read as $c"; }
                $ips[$f] = $c;
            } elseif ($f === 'Subnet Mask') {
                if (self::maskBits($s) < 0) { $errors[] = "Subnet Mask \"$s\" is not a valid mask"; }
                else { $ips[$f] = self::canonIp($s) ?? $s; }
            } else {
                if (!preg_match('/^\d{1,4}$/D', $s) || (int)$s < 1 || (int)$s > 4094) { $errors[] = "$f \"$s\" must be a number from 1 to 4094"; }
                else { $ips[$f] = (string)(int)$s; }
            }
        }
        $hasDevice = false;
        foreach (self::UNIQ as $f) { if (!empty($ips[$f])) { $hasDevice = true; break; } }
        if (!$hasDevice) { $errors[] = 'no device IPs in this row (RTU, PLC, HMI or Moxa)'; }

        $mask = $ips['Subnet Mask'] ?? $cfg['mask'];
        $rowInfra = [];
        foreach (self::INFRA as $f) { if (!empty($ips[$f])) { $rowInfra[$ips[$f]] = $f; } }
        foreach (self::UNIQ as $f) {
            if (empty($ips[$f])) { continue; }
            $edge = self::edgeAddress($ips[$f], $mask);
            if ($edge !== '') { $errors[] = "$f {$ips[$f]} is the $edge address of its subnet"; }
            if (isset($rowInfra[$ips[$f]])) { $errors[] = "$f {$ips[$f]} is the same as {$rowInfra[$ips[$f]]}"; }
        }
        $errors = array_merge($errors, self::checkIps($ips, $idx));

        // non-blocking notes: imported data may come from older rules
        $gcpKnown = array_key_exists($gcp, $cfg['gcps']);
        $vendorKnown = in_array($vendor, $cfg['vendors'], true);
        if ($gcp !== '' && !$gcpKnown) { $warnings[] = "GCP & Ring $gcp is not configured, so this record can be edited but its IPs cannot be regenerated"; }
        if ($vendor !== '' && !$vendorKnown) { $warnings[] = "Vendor $vendor is not configured"; }
        if ($gcpKnown && $vendorKnown && !$errors) {
            $match = false;
            foreach ($cfg['blocks'] as $b) {
                if ($b['gcp'] === $gcp && $b['rule']['name'] === $vendor && self::ruleHost($b, $ips)) { $match = true; break; }
            }
            if (!$match) { $warnings[] = "the IPs do not follow the $gcp / $vendor rule; they are kept as they are and stay reserved"; }
            [$rv, $pv] = $cfg['gcps'][$gcp];
            if ((!empty($ips['RTU VLAN']) && $ips['RTU VLAN'] !== $rv) || (!empty($ips['PLC VLAN']) && $ips['PLC VLAN'] !== $pv)) {
                $warnings[] = "the VLANs differ from $gcp ($rv / $pv)";
            }
        }
        if (!empty($ips['Gateway-1']) && !empty($ips['RTU IP-1']) && !self::sameSubnet($ips['Gateway-1'], $ips['RTU IP-1'], $mask)) {
            $warnings[] = 'RTU IP-1 is not in the same subnet as Gateway-1';
        }
        $date = self::importDate($row['Date'] ?? null);
        if ($date !== '' && !self::isIsoDate($date)) { $warnings[] = "Date \"$date\" is not YYYY-MM-DD; it is kept as text"; }

        if ($errors) { return ['line' => $line, 'name' => $name, 'record' => null, 'errors' => $errors, 'warnings' => $warnings]; }
        $rec = ['name' => $name !== '' ? $name : 'UNKNOWN', 'gcp' => $gcp, 'vendor' => $vendor, 'engineer' => $eng, 'date' => $date, 'ips' => $ips];
        return ['line' => $line, 'name' => $name, 'record' => $rec, 'errors' => [], 'warnings' => $warnings];
    }

    /** Validate rows in order; each accepted row is added to the index so later rows are checked against it. */
    public static function checkImportRows(array $rows, array $idx, array $cfg): array
    {
        $out = [];
        foreach ($rows as [$line, $row]) {
            $res = self::checkImportRow($row, $idx, $cfg, (int)$line);
            if ($res['record']) { self::indexAdd($idx, $res['record']['name'], $res['record']['ips'], 'file'); }
            $out[] = $res;
        }
        return $out;
    }
}
