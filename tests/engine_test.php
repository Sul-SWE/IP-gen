<?php
// Engine tests (SRS section 4.6 and the prototype's tests). Run:  php tests/engine_test.php
declare(strict_types=1);
require __DIR__ . '/../server/Engine.php';

$pass = 0; $fail = 0;
function t(string $name, bool $ok, string $detail = ''): void
{
    global $pass, $fail;
    $ok ? $pass++ : $fail++;
    echo ($ok ? 'PASS ' : 'FAIL ') . $name . ($ok || $detail === '' ? '' : " :: $detail") . "\n";
}

// the starting rules of database/ipgen.sql (dummy test values from the SRS)
$f = fn(string $field, string $net, int $a, int $b) => ['field' => $field, 'net' => $net, 'a' => $a, 'b' => $b];
$d = [
    'facilities' => ['UTMN', 'HRDH', 'HWYH', 'SDGM'],
    'gcp_rings' => [['HDGCP1-R1', 18, 1, '1800', '1801'], ['SHGCP1-R1', 19, 1, '1810', '1811'], ['HWGCP1-R1', 20, 1, '1820', '1821'], ['UTGCP1-R1', 21, 1, '1830', '1831']],
    'vendors' => [
        ['name' => 'Yokogawa', 'capacity' => 39, 'octets' => ['A' => 20, 'B' => 21, 'M' => 10], 'fields' => [
            $f('RTU IP-1', 'A', 1, 168), $f('RTU IP-2', 'B', 1, 168), $f('PLC IP-1', 'A', 1, 84), $f('PLC IP-2', 'B', 1, 84),
            $f('RTU Internal IP-1', 'A', 1, 0), $f('RTU Internal IP-2', 'B', 1, 0), $f('RTU-HMI IP', 'A', 1, 210), $f('IES Moxa IP', 'M', 1, 0),
            $f('Engg. Laptop IP', 'A', 0, 250), $f('Gateway-1', 'A', 0, 253), $f('Gateway-2', 'B', 0, 253)]],
        ['name' => 'Honeywell', 'capacity' => 62, 'octets' => ['A' => 100, 'B' => 101, 'M' => 11], 'fields' => [
            $f('RTU IP-1', 'A', 4, -3), $f('RTU IP-2', 'A', 4, -2), $f('PLC IP-1', 'A', 4, -1), $f('PLC IP-2', 'A', 4, 0),
            $f('RTU-HMI IP', 'B', 1, 0), $f('IES Moxa IP', 'M', 1, 0), $f('Engg. Laptop IP', 'A', 0, 250), $f('Gateway-1', 'A', 0, 253), $f('Gateway-2', 'B', 0, 253)]],
    ],
];
function vrule(array $d, string $name): array { foreach ($d['vendors'] as $v) { if ($v['name'] === $name) { return ['name' => $v['name'], 'capacity' => $v['capacity'], 'fields' => $v['fields']]; } } throw new Exception($name); }
function blk(array $d, string $gcp, string $vendor, ?int $o2 = null): array
{
    foreach ($d['gcp_rings'] as [$code, $o1, $oo2, $rv, $pv]) {
        if ($code !== $gcp) { continue; }
        foreach ($d['vendors'] as $v) {
            if ($v['name'] === $vendor) {
                return ['gcp' => $code, 'octet1' => $o1, 'octet2' => $o2 ?? $oo2, 'octets' => $v['octets'], 'rule' => vrule($d, $vendor), 'rtu_vlan' => $rv, 'plc_vlan' => $pv, 'mask' => '255.255.255.0'];
            }
        }
    }
    throw new Exception($gcp);
}
function busyOf(array $records): array { $idx = Engine::newIndex(); foreach ($records as $r) { Engine::indexAdd($idx, $r['name'], $r['ips'], 'active'); } return Engine::busy($idx); }
$Y = blk($d, 'HDGCP1-R1', 'Yokogawa');
$all = [];
foreach ($d['gcp_rings'] as $g) { foreach ($d['vendors'] as $v) { $all[] = blk($d, $g[0], $v['name']); } }

/* ---------- 4.6 vectors ---------- */
$r = Engine::build($Y, 1);
t('Yokogawa n=1: RTU 18.1.20.169 / 18.1.21.169, PLC .85, Internal .1, HMI .211, Moxa 18.1.10.1',
  $r['RTU IP-1'] === '18.1.20.169' && $r['RTU IP-2'] === '18.1.21.169' && $r['PLC IP-1'] === '18.1.20.85' && $r['PLC IP-2'] === '18.1.21.85'
  && $r['RTU Internal IP-1'] === '18.1.20.1' && $r['RTU-HMI IP'] === '18.1.20.211' && $r['IES Moxa IP'] === '18.1.10.1'
  && $r['Gateway-1'] === '18.1.20.253' && $r['Engg. Laptop IP'] === '18.1.20.250' && $r['RTU VLAN'] === '1800');
$h = blk($d, 'SHGCP1-R1', 'Honeywell');
$r = Engine::build($h, 1);
t('Honeywell k=1: RTU 19.1.100.1, PLC-2 .4, HMI 19.1.101.1, no RTU Internal', $r['RTU IP-1'] === '19.1.100.1' && $r['PLC IP-2'] === '19.1.100.4' && $r['RTU-HMI IP'] === '19.1.101.1' && !isset($r['RTU Internal IP-1']));
$ok = true;
for ($k = 1; $k <= 62; $k++) { $s = 4 * ($k - 1) + 1; $r = Engine::build($h, $k); $ok = $ok && $r['RTU IP-1'] === "19.1.100.$s" && $r['PLC IP-2'] === '19.1.100.' . ($s + 3) && $r['RTU-HMI IP'] === "19.1.101.$k"; }
t('Honeywell formula matches the SRS for every k', $ok);

/* ---------- fill every range ---------- */
$recs = []; $early = [];
foreach ($all as $b) {
    for ($i = 0; $i < $b['rule']['capacity']; $i++) {
        $a = Engine::allocate($b, busyOf($recs));
        if (!empty($a['full'])) { $early[] = $b['gcp'] . $b['rule']['name']; break; }
        $recs[] = ['name' => 'T-' . count($recs), 'gcp' => $b['gcp'], 'vendor' => $b['rule']['name'], 'ips' => $a['ips']];
    }
    if (empty(Engine::allocate($b, busyOf($recs))['full'])) { $early[] = $b['gcp'] . $b['rule']['name'] . ' not full'; }
}
t('Every range fills to its limit and then reports full (no overflow)', !$early && count($recs) === 404, implode(',', $early));
$seen = []; $dup = 0; $bad = 0;
foreach ($recs as $x) { foreach (Engine::UNIQ as $f) { if (empty($x['ips'][$f])) { continue; } $ip = $x['ips'][$f]; if (isset($seen[$ip])) { $dup++; } $seen[$ip] = 1; $host = (int)explode('.', $ip)[3]; if ($host < 1 || $host > 249) { $bad++; } } }
t('No duplicate device IP across ' . count($seen) . ' addresses; all hosts 1..249, never .250 / .253', $dup === 0 && $bad === 0, "$dup dup, $bad bad");
$y = array_values(array_filter($recs, fn($x) => $x['gcp'] === 'HDGCP1-R1' && $x['vendor'] === 'Yokogawa'));
$rest = array_values(array_filter($recs, fn($x) => $x !== $y[4]));
t('A freed number (delete forever) is reused first', Engine::allocate($Y, busyOf($rest))['n'] === 5);
t('A record in the trash keeps its numbers reserved', !empty(Engine::allocate($Y, busyOf($recs))['full']));
$a = Engine::allocate($Y, busyOf([['name' => 'UTMN-1', 'ips' => ['RTU IP-1' => Engine::build($Y, 1)['RTU IP-1']]]]));
t('An IP already used makes allocation skip that number', $a['n'] === 2 && $a['skipped'] === [1]);
t('Same GCP in Ring 2 does not clash', Engine::allocate(blk($d, 'HDGCP1-R1', 'Yokogawa', 2), busyOf([['name' => 'UTMN-1', 'ips' => Engine::build($Y, 1)]]))['n'] === 1);
t('Allocation skips a host whose IP is another record\'s gateway', Engine::allocate($Y, busyOf([['name' => 'USED', 'ips' => ['Gateway-1' => '18.1.20.169']]]))['n'] === 2);
t('Old data with leading zeros still blocks the same address', Engine::allocate($Y, busyOf([['name' => 'UTMN-5', 'ips' => ['RTU IP-1' => '018.001.020.169']]]))['n'] === 2);

/* ---------- names, people, addresses, dates ---------- */
$fac = $d['facilities'];
t('Name format', Engine::nameFormatError('utmn-1000', $fac) === '' && Engine::nameFormatError('UTMN', $fac) !== '' && Engine::nameFormatError('ABCD-12', $fac) !== ''
  && Engine::nameFormatError('UTMN-12ab', $fac) !== '' && Engine::nameFormatError('UTMN-123456', $fac) !== '' && Engine::isPlaceholder('Used') && !Engine::isPlaceholder('UTMN-1'));
t('Engineer names', Engine::cleanPerson('  Eng   A ') === 'Eng A' && Engine::checkPerson('Eng A') === '' && Engine::checkPerson("O'Neil-Smith Jr.") === ''
  && Engine::checkPerson('محمد علي') === '' && Engine::checkPerson('E') !== '' && Engine::checkPerson('<b>x</b>') !== '' && Engine::checkPerson('12345') !== '');
t('IPv4 helpers', Engine::canonIp('018.001.020.07') === '18.1.20.7' && Engine::canonIp('18.1.20.256') === null && Engine::maskBits('255.255.255.0') === 24
  && Engine::maskBits('255.0.255.0') === -1 && Engine::edgeAddress('18.1.20.0', '255.255.255.0') === 'network' && Engine::edgeAddress('18.1.20.255', '255.255.255.0') === 'broadcast');
t('Rule host', Engine::ruleHost($Y, Engine::build($Y, 7)) === 7 && Engine::ruleHost(blk($d, 'HDGCP1-R1', 'Honeywell'), Engine::build($Y, 7)) === 0);
t('Dates', Engine::isIsoDate('2026-11-04') && !Engine::isIsoDate('2026-13-01') && !Engine::isIsoDate('2026-02-30') && Engine::importDate(46000) === '2025-12-09' && Engine::importDate('04/11/2026') === '04/11/2026');

/* ---------- vendor rule safety ---------- */
$yr = vrule($d, 'Yokogawa');
t('Seed rules are safe', Engine::validateRule($yr, ['A' => 20, 'B' => 21, 'M' => 10]) === [] && Engine::validateRule(vrule($d, 'Honeywell'), ['A' => 100, 'B' => 101, 'M' => 11]) === []);
$mod = function (array $rule, string $field, int $b) { foreach ($rule['fields'] as &$f) { if ($f['field'] === $field) { $f['b'] = $b; } } return $rule; };
t('Unsafe rules are refused', Engine::validateRule(['capacity' => 90] + $yr) !== [] && str_contains(implode(' ', Engine::validateRule(['capacity' => 5] + $mod($yr, 'RTU IP-1', 252))), 'Gateway-1')
  && str_contains(implode(' ', Engine::validateRule(['capacity' => 5] + $mod($yr, 'RTU IP-1', 84))), 'already used') && Engine::validateRule($yr, ['A' => 20, 'B' => 20, 'M' => 10]) !== []);

/* ---------- import rows ---------- */
$cfg = ['facilities' => $fac, 'blocks' => $all, 'gcps' => [], 'vendors' => ['Yokogawa', 'Honeywell'], 'mask' => '255.255.255.0'];
foreach ($d['gcp_rings'] as $g) { $cfg['gcps'][$g[0]] = [$g[3], $g[4]]; }
$row = fn(int $n, array $x = []) => array_merge(['Facility Name' => "UTMN-$n", 'GCP & Ring' => 'HDGCP1-R1', 'Vendor' => 'Yokogawa', 'Date' => '2026-01-02', 'TSU PAN Engineer' => 'Eng A'], Engine::build($Y, $n), $x);
$run = function (array $rows, array $existing = []) use ($cfg) {
    $idx = Engine::newIndex();
    foreach ($existing as $e) { Engine::indexAdd($idx, $e[0], $e[1], $e[2]); }
    $l = 2; return Engine::checkImportRows(array_map(function ($r) use (&$l) { return [$l++, $r]; }, $rows), $idx, $cfg);
};
$ex = [['UTMN-1', Engine::build($Y, 1), 'active'], ['UTMN-2', Engine::build($Y, 2), 'trash']];
$res = $run([$row(3)], $ex);
t('Import: clean row accepted without notes', $res[0]['record'] !== null && $res[0]['warnings'] === []);
t('Import: name of active / trashed record refused', $run([$row(9, ['Facility Name' => 'UTMN-1'])], $ex)[0]['record'] === null && str_contains(implode(' ', $run([$row(9, ['Facility Name' => 'utmn-2'])], $ex)[0]['errors']), 'trash'));
t('Import: IP of a trashed record and cross-column IP refused', $run([$row(2, ['Facility Name' => 'UTMN-50'])], $ex)[0]['record'] === null
  && $run([$row(9, ['Facility Name' => 'UTMN-60', 'RTU IP-1' => Engine::build($Y, 1)['PLC IP-1']])], $ex)[0]['record'] === null);
$two = $run([$row(10), $row(10, ['Facility Name' => 'UTMN-61'])]);
t('Import: duplicate of an earlier row in the same file refused', $two[0]['record'] !== null && $two[1]['record'] === null);
t('Import: same IP twice in one row, octet 300, gateway address, network address, bad VLAN, bad mask refused',
  $run([$row(10, ['PLC IP-1' => '18.1.20.178'])])[0]['record'] === null && $run([$row(11, ['RTU IP-1' => '18.1.20.300'])])[0]['record'] === null
  && $run([$row(12, ['RTU IP-1' => '18.1.20.253'])])[0]['record'] === null && $run([$row(13, ['RTU-HMI IP' => '18.1.20.0'])])[0]['record'] === null
  && $run([$row(14, ['RTU VLAN' => '5000'])])[0]['record'] === null && $run([$row(15, ['Subnet Mask' => '255.0.255.0'])])[0]['record'] === null);
$used = $run([['Facility Name' => 'Used', 'RTU IP-1' => '30.1.1.1'], ['Facility Name' => 'Used', 'RTU IP-1' => '30.1.1.2']]);
t('Import: placeholder names may repeat', $used[0]['record'] !== null && $used[1]['record'] !== null);
$lz = $run([$row(16, ['RTU IP-1' => '18.1.20.017'])])[0];
t('Import: leading zeros normalised with a note', $lz['record'] !== null && $lz['record']['ips']['RTU IP-1'] === '18.1.20.17' && $lz['warnings'] !== []);
t('Import: IPs off the rule and unknown GCP are kept with a note', str_contains(implode(' ', $run([$row(17, ['RTU IP-1' => '18.1.20.5'])])[0]['warnings']), 'do not follow')
  && str_contains(implode(' ', $run([$row(18, ['GCP & Ring' => 'OLDGCP-R9'])])[0]['warnings']), 'not configured'));
$num = $run([$row(19, ['RTU VLAN' => 1800.0, 'Date' => 46000])])[0];
t('Import: Excel numbers (VLAN 1800.0, serial date)', $num['record'] !== null && $num['record']['ips']['RTU VLAN'] === '1800' && $num['record']['date'] === '2025-12-09');
t('Import: markup is refused as a name', $run([$row(23, ['Facility Name' => '<img src=x onerror=alert(1)>'])])[0]['record'] === null);

echo "\n$pass passed, $fail failed\n";
exit($fail ? 1 : 0);
