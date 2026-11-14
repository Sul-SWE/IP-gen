<?php
/** Excel import (preview -> confirm -> undo last) and export. Import only ever adds rows. */

declare(strict_types=1);

final class Importer
{
    public const MAX_BYTES = 5 * 1024 * 1024;
    public const MAX_ROWS = 5000;
    private const MAX_UNZIPPED = 60 * 1024 * 1024;
    private const PREVIEW_TTL = 30 * 60;
    private const REQUIRED = ['Facility Name', 'RTU IP-1'];
    private const ALIASES = ['name' => 'Facility Name', 'facility' => 'Facility Name', 'gcp' => 'GCP & Ring', 'gcpring' => 'GCP & Ring',
        'engineer' => 'TSU PAN Engineer', 'tsupanengineer' => 'TSU PAN Engineer'];

    private static function key($s): string
    {
        return preg_replace('/[^a-z0-9]/', '', str_replace('&', 'and', strtolower(Engine::text($s)))) ?? '';
    }

    private static function headerMap(array $cells): array
    {
        $known = [];
        foreach (Engine::columns() as $c) { $known[self::key($c)] = $c; }
        $known += self::ALIASES;
        $out = [];
        ksort($cells);
        foreach ($cells as $i => $v) {
            $col = $known[self::key($v)] ?? null;
            if ($col !== null && !in_array($col, $out, true)) { $out[$i] = $col; }
        }
        return $out;
    }

    /** Reads the data sheet. Returns [rows as [excel line, [column => value]], known column count, sheet name]. */
    public static function parse(string $data, string $filename): array
    {
        if (!preg_match('/\.xlsx$/i', $filename)) {
            throw ApiError::bad('Please choose an Excel file (.xlsx). Older .xls files: open in Excel and use Save As .xlsx. Nothing was imported.', [], 'wrong_type');
        }
        if (strlen($data) > self::MAX_BYTES) { throw new ApiError(413, 'too_large', 'This file is larger than 5 MB. Nothing was imported.'); }
        if ($data === '') { throw ApiError::bad('This file is empty. Nothing was imported.', [], 'empty_file'); }
        try {
            $x = new XlsxReader($data, self::MAX_UNZIPPED);
            $sheets = $x->sheets();
        } catch (XlsxError $e) {
            if ($e->getMessage() === 'too large unpacked') { throw ApiError::bad('This file is too large when unpacked. Nothing was imported.', [], 'too_large'); }
            throw ApiError::bad('This file could not be read. It may be damaged or not a real Excel file. Nothing was imported.', [], 'unreadable');
        }
        foreach ($sheets as [$title, $path]) {
            $head = 0; $map = []; $rows = []; $tooMany = false;
            try {
                $x->rows($path, function (int $line, array $cells) use (&$head, &$map, &$rows, &$tooMany) {
                    if (!$map) {
                        if ($line > 15) { return false; }
                        $m = self::headerMap($cells);
                        if (!array_diff(self::REQUIRED, $m)) { $head = $line; $map = $m; }
                        return true;
                    }
                    $blank = true;
                    foreach ($cells as $v) { if ($v !== null && trim(Engine::text($v)) !== '') { $blank = false; break; } }
                    if ($blank) { return true; }
                    if (count($rows) >= self::MAX_ROWS) { $tooMany = true; return false; }
                    $o = [];
                    foreach ($map as $i => $col) { $o[$col] = $cells[$i] ?? null; }
                    $rows[] = [$line, $o];
                    return true;
                });
            } catch (XlsxError $e) {
                throw ApiError::bad('This file could not be read. It may be damaged or not a real Excel file. Nothing was imported.', [], 'unreadable');
            }
            if ($tooMany) { throw ApiError::bad('The sheet has more than ' . self::MAX_ROWS . ' rows. Split it into smaller files. Nothing was imported.', [], 'too_many_rows'); }
            if ($head) {
                if (!$rows) { throw ApiError::bad('No data rows were found under the column names. Nothing was imported.', [], 'no_rows'); }
                return [$rows, count($map), $title];
            }
        }
        throw ApiError::bad('No sheet has the column names Facility Name and RTU IP-1 in its first rows. Use the same column names as an exported file. Nothing was imported.', [], 'wrong_columns');
    }

    private static function short(array $items, int $limit = 4): array
    {
        return count($items) > $limit ? array_merge(array_slice($items, 0, $limit), ['and ' . (count($items) - $limit) . ' more']) : $items;
    }

    private static function dir(): string
    {
        $d = __DIR__ . '/storage/previews';
        if (!is_dir($d)) { @mkdir($d, 0770, true); }
        return $d;
    }

    private static function cleanup(): void
    {
        foreach (glob(self::dir() . '/*.json') ?: [] as $f) { if (@filemtime($f) < time() - self::PREVIEW_TTL) { @unlink($f); } }
    }

    public static function preview(Db $db, string $data, string $filename): array
    {
        [$rows, $ncols, $sheet] = self::parse($data, $filename);
        $rules = Rules::load($db);
        $results = Engine::checkImportRows($rows, Records::buildIndex($db), $rules->importConfig());
        $add = array_values(array_filter($results, fn($r) => $r['record'] !== null));
        self::cleanup();
        $token = rtrim(strtr(base64_encode(random_bytes(24)), '+/', '-_'), '=');
        $name = Records::cut($filename, 80);
        $ok = file_put_contents(self::dir() . "/$token.json", jenc(['rows' => $rows, 'filename' => $name,
            'expected' => array_map(fn($r) => [$r['line'], $r['record']['name']], $add)]));
        if ($ok === false) { throw new RuntimeException('cannot write import preview'); }
        $issues = [];
        foreach ($results as $r) {
            if ($r['record'] === null || $r['warnings']) {
                $issues[] = ['line' => $r['line'], 'name' => $r['name'] !== '' ? $r['name'] : '(empty)', 'add' => $r['record'] !== null,
                    'reasons' => self::short($r['record'] !== null ? $r['warnings'] : $r['errors'])];
            }
        }
        return ['token' => $token, 'filename' => $name, 'sheet' => $sheet, 'rows' => count($rows), 'columns' => $ncols,
            'will_add' => count($add), 'will_skip' => count($results) - count($add),
            'with_notes' => count(array_filter($add, fn($r) => (bool)$r['warnings'])),
            'issues' => array_slice($issues, 0, 300), 'issues_total' => count($issues)];
    }

    /** Write the previewed rows (inside Db::write). */
    public static function confirm(Db $db, string $token, string $actor): array
    {
        $who = Records::person($actor, 'Your name');
        $file = self::dir() . '/' . (preg_match('/^[A-Za-z0-9_\-]{10,80}$/', $token) ? $token : 'invalid') . '.json';
        if (!is_file($file) || @filemtime($file) < time() - self::PREVIEW_TTL) {
            throw ApiError::conflict('This import preview has expired. Choose the file again.', [], 'preview_expired');
        }
        $pv = jdec(file_get_contents($file));
        $rules = Rules::load($db);
        $eblocks = $rules->engineBlocks();
        $results = Engine::checkImportRows($pv['rows'], Records::buildIndex($db), $rules->importConfig());
        $add = array_values(array_filter($results, fn($r) => $r['record'] !== null));
        if (array_map(fn($r) => [$r['line'], $r['record']['name']], $add) !== $pv['expected']) {
            @unlink($file);
            throw ApiError::conflict('The stored data changed after the preview (another change was saved). Nothing was imported. Import the file again to see a new preview.', [], 'preview_changed');
        }
        if (!$add) { throw ApiError::bad('No row of this file can be imported. Nothing was imported.', [], 'nothing_to_import'); }
        $now = $db->now();
        $batch = 'imp-' . bin2hex(random_bytes(8));
        foreach (array_chunk($add, 200) as $chunk) {
            foreach ($chunk as $res) {
                $rec = $res['record'];
                $placeholder = Engine::isPlaceholder($rec['name']) || $rec['name'] === 'UNKNOWN';
                $blockId = null; $host = null;
                foreach ($eblocks as $b) {
                    if ($b['gcp'] === $rec['gcp'] && $b['rule']['name'] === $rec['vendor']) {
                        $n = Engine::ruleHost($b, $rec['ips']);
                        if ($n) { $blockId = $b['block_id']; $host = $n; break; }
                    }
                }
                $id = Records::guard(fn() => $db->insert('INSERT INTO records (name, name_key, gcp_code, vendor, block_id, host_no, engineer_name, record_date, status, shared_fields, import_batch_id, version, created_at, updated_at, deleted_by) '
                    . "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, 1, ?, ?, '')",
                    [$rec['name'], $placeholder ? null : strtolower($rec['name']), $rec['gcp'], $rec['vendor'], $blockId, $host, $rec['engineer'], $rec['date'],
                     Records::sharedOf($rec['ips']), $batch, $now, $now]));
                $vals = []; $params = [];
                foreach (Engine::ipFields() as $f) {
                    if (empty($rec['ips'][$f])) { continue; }
                    $vals[] = '(?, ?, ?, ?)';
                    array_push($params, $id, $f, $rec['ips'][$f], in_array($f, Engine::UNIQ, true) ? $rec['ips'][$f] : null);
                }
                if ($vals) { Records::guard(fn() => $db->q('INSERT INTO ip_assignments (record_id, field, ip, uniq_ip) VALUES ' . implode(',', $vals), $params)); }
            }
        }
        $skipped = array_values(array_filter($results, fn($r) => $r['record'] === null));
        Rules::setSetting($db, 'last_import', substr(jenc(['batch' => $batch, 'file' => $pv['filename'], 'at' => fmt_dt($now), 'who' => $who, 'count' => count($add)]), 0, 255));
        Records::addLog($db, $who, 'Imported', count($add) . ' row(s)', "From {$pv['filename']}; " . count($skipped) . ' row(s) skipped', $batch);
        @unlink($file);
        return ['imported' => count($add), 'skipped' => count($skipped), 'filename' => $pv['filename'],
            'skipped_rows' => array_map(fn($r) => ['line' => $r['line'], 'name' => $r['name'] !== '' ? $r['name'] : 'no name', 'reasons' => self::short($r['errors'], 2)], array_slice($skipped, 0, 15))];
    }

    public static function lastImport(Db $db): ?array
    {
        $raw = Rules::getSetting($db, 'last_import', '');
        $info = $raw === '' ? null : json_decode($raw, true);
        if (!is_array($info) || !isset($info['batch'])) { return null; }
        $rows = $db->all('SELECT name, version, status FROM records WHERE import_batch_id = ?', [$info['batch']]);
        $why = '';
        if (count($rows) < $info['count']) {
            $why = ($info['count'] - count($rows)) . ' of its rows were deleted forever';
        } else {
            $changed = array_map(fn($r) => $r['name'], array_filter($rows, fn($r) => (int)$r['version'] !== 1 || $r['status'] !== 'active'));
            $changed = array_values($changed);
            if ($changed) { $why = 'these rows were changed since: ' . implode(', ', array_slice($changed, 0, 5)) . (count($changed) > 5 ? ' +' . (count($changed) - 5) : ''); }
        }
        return $info + ['can_undo' => $why === '', 'why' => $why];
    }

    public static function undoLast(Db $db, string $actor, ?string $batch = null): array
    {
        $who = Records::person($actor, 'Your name');
        $info = self::lastImport($db);
        if (!$info || ($batch !== null && $batch !== '' && $batch !== $info['batch'])) {
            throw ApiError::conflict('There is no import to undo, or another import happened meanwhile. Nothing was removed.', [], 'no_import');
        }
        if (!$info['can_undo']) {
            throw ApiError::conflict("The last import cannot be undone: {$info['why']}. Undo only works while every imported row is unchanged.", [], 'import_changed');
        }
        $db->q('DELETE FROM records WHERE import_batch_id = ?', [$info['batch']]);
        Rules::setSetting($db, 'last_import', '');
        Records::addLog($db, $who, 'Import undone', "{$info['count']} row(s)", "Removed the rows imported from {$info['file']} on {$info['at']}", $info['batch']);
        return ['removed' => $info['count'], 'filename' => $info['file']];
    }

    /** All active records with the worksheet columns. Cells are written as text, never as formulas. */
    public static function export(Db $db): array
    {
        $recs = $db->all("SELECT * FROM records WHERE status = 'active' ORDER BY id");
        $ips = Records::ipsOf($db, $recs);
        $rows = [];
        foreach ($recs as $r) {
            $i = $ips[(int)$r['id']];
            $row = [$r['name'], $r['gcp_code'], $r['vendor'], $r['record_date'], $r['engineer_name']];
            foreach (Engine::ALL_FIELDS as $f) { $row[] = $i[$f] ?? ''; }
            $rows[] = $row;
        }
        $cols = Engine::columns();
        $widths = array_map(fn($c) => max(strlen($c) + 2, in_array($c, Engine::ipFields(), true) ? 16 : 13), $cols);
        return [XlsxWriter::build('IPs', $cols, $rows, $widths), 'IP-Generator-' . $db->today() . '.xlsx', count($rows)];
    }
}
