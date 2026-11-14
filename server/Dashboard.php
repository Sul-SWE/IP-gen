<?php
/** Numbers for the dashboard. */

declare(strict_types=1);

final class Dashboard
{
    private const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

    /** Usage of the active block of every GCP & Ring + vendor (trashed records count as used). */
    public static function ranges(Db $db, ?Rules $rules = null): array
    {
        $rules = $rules ?? Rules::load($db);
        $busy = Engine::busy(Records::buildIndex($db));
        $out = [];
        foreach ($rules->gcps as $g) {
            if (!$g['active']) { continue; }
            foreach ($rules->vendors as $v) {
                if (!$v['active']) { continue; }
                $mine = array_values(array_filter($rules->blocks, fn($b) => $b['gcp_id'] === $g['id'] && $b['vendor_id'] === $v['id']));
                $blk = null;
                foreach ($mine as $b) { if ($b['status'] === 'active') { $blk = $b; break; } }
                $item = ['gcp' => $g['code'], 'vendor' => $v['name'], 'prefix' => $g['octet1'] . '.' . $g['octet2'], 'rtu_vlan' => $g['rtu_vlan'], 'plc_vlan' => $g['plc_vlan'],
                    'planned' => (bool)array_filter($mine, fn($b) => $b['status'] === 'planned'),
                    'retired' => count(array_filter($mine, fn($b) => $b['status'] === 'retired')),
                    'block_seq' => $blk ? $blk['seq'] : 0, 'used' => 0, 'max' => 0, 'next' => 0, 'next_rtu' => '', 'state' => 'none'];
                if ($blk) {
                    $eb = $rules->engineBlock($blk);
                    [$used, $cap, $next] = Engine::usage($eb, $busy);
                    $item['used'] = $used; $item['max'] = $cap; $item['next'] = $next;
                    $item['next_rtu'] = $next ? (Engine::build($eb, $next)['RTU IP-1'] ?? '') : '';
                    $item['state'] = $used >= $cap ? 'full' : ($used / $cap >= $rules->warnAt ? 'warn' : 'ok');
                }
                $out[] = $item;
            }
        }
        return $out;
    }

    public static function build(Db $db): array
    {
        $rules = Rules::load($db);
        $rng = self::ranges($db, $rules);
        $active = $db->all("SELECT name, vendor, record_date FROM records WHERE status = 'active'");
        $c = Records::counts($db);
        $today = $db->today();
        $cut = gmdate('Y-m-d', strtotime($today . ' UTC') - 30 * 86400);
        $used = array_sum(array_column($rng, 'used')); $total = array_sum(array_column($rng, 'max'));
        $attention = [];
        foreach ($rng as $r) { if ($r['state'] === 'warn' || $r['state'] === 'full') { $attention[] = "{$r['gcp']} / {$r['vendor']}" . ($r['state'] === 'full' ? ' (full)' : ''); } }

        $areas = [];
        foreach ($rules->activeFacilityCodes() as $code) { $areas[$code] = []; }
        $vendorNames = array_map(fn($v) => $v['name'], $rules->vendors);
        $codes = $rules->facilityCodes();
        $vt = [];
        foreach ($active as $a) {
            $p = Engine::splitName($a['name']);
            $area = $p && in_array($p[0], $codes, true) ? $p[0] : 'Other';
            $ven = in_array($a['vendor'], $vendorNames, true) ? $a['vendor'] : 'Other';
            $areas[$area][$ven] = ($areas[$area][$ven] ?? 0) + 1;
            $vt[$ven] = ($vt[$ven] ?? 0) + 1;
        }
        $months = [];
        [$y, $m] = array_map('intval', explode('-', substr($today, 0, 7)));
        for ($i = 5; $i >= 0; $i--) {
            $yy = $y; $mm = $m - $i;
            while ($mm < 1) { $yy--; $mm += 12; }
            $key = sprintf('%04d-%02d', $yy, $mm);
            $n = 0;
            foreach ($active as $a) { if (Engine::isIsoDate($a['record_date']) && str_starts_with($a['record_date'], $key)) { $n++; } }
            $months[] = ['key' => $key, 'label' => self::MONTHS[$mm - 1], 'count' => $n];
        }
        $recent30 = 0;
        foreach ($active as $a) { if (Engine::isIsoDate($a['record_date']) && $a['record_date'] >= $cut) { $recent30++; } }
        $recent = $db->all('SELECT * FROM audit_log ORDER BY id DESC LIMIT 5');
        $areaList = [];
        foreach ($areas as $a => $v) { $areaList[] = ['area' => (string)$a, 'by_vendor' => (object)$v, 'total' => array_sum($v)]; }
        return [
            'kpis' => ['active' => $c['active'], 'trash' => $c['trash'], 'used' => $used, 'total' => $total, 'free' => $total - $used,
                'recent30' => $recent30, 'since' => $cut, 'attention' => $attention, 'any_full' => (bool)array_filter($rng, fn($r) => $r['state'] === 'full')],
            'warn_at' => $rules->warnAt,
            'ranges' => $rng,
            'vendors' => $vendorNames,
            'areas' => $areaList,
            'vendor_totals' => (object)$vt,
            'months' => $months,
            'recent' => array_map(fn($x) => ['at' => fmt_dt($x['at']), 'who' => $x['engineer_name'], 'action' => $x['action'], 'name' => $x['record_name'], 'details' => $x['details']], $recent),
        ];
    }
}
