<?php
/**
 * PMT file: an Excel template whose cells contain field names in braces, e.g. {RTU IP-1}.
 * For one record, every {Field} is replaced by the record's value; everything else in the file
 * (layout, colours, borders, other text) stays exactly as it is.
 */

declare(strict_types=1);

final class Pmt
{
    public const MAX_BYTES = 2 * 1024 * 1024;
    private const MAX_UNZIPPED = 30 * 1024 * 1024;
    private const TOKEN = '/\{([^{}<>\r\n]{1,40})\}/';

    /** Every field a template may use. */
    public static function fields(): array
    {
        return array_merge(Engine::columns(), ['Host Number', 'Generated On']);
    }

    private static function key(string $s): string
    {
        return strtolower(trim(preg_replace('/\s+/', ' ', html_entity_decode($s, ENT_QUOTES | ENT_XML1, 'UTF-8')) ?? ''));
    }

    private static function known(): array
    {
        $k = [];
        foreach (self::fields() as $f) { $k[self::key($f)] = $f; }
        return $k;
    }

    /** The template in use: the one uploaded in Settings, or the default one in database/. */
    public static function templatePath(): string
    {
        $custom = __DIR__ . '/storage/pmt-template.xlsx';
        return is_file($custom) ? $custom : dirname(__DIR__) . '/database/pmt-template.xlsx';
    }

    public static function isCustom(): bool { return is_file(__DIR__ . '/storage/pmt-template.xlsx'); }

    /** The XML parts of the workbook that can hold cell text (shared strings and the sheets). */
    private static function textParts(Zip $zip): array
    {
        return array_values(array_filter($zip->names(), fn($n) => $n === 'xl/sharedStrings.xml' || preg_match('#^xl/worksheets/[^/]+\.xml$#', $n)));
    }

    /**
     * Checks a template. Returns the fields it uses. Refuses files that are not .xlsx,
     * have no {Field} at all, or contain a {Name} that is not a known field (a typo would stay unfilled).
     */
    public static function check(string $data): array
    {
        if (strlen($data) > self::MAX_BYTES) { throw new ApiError(413, 'too_large', 'The template is larger than 2 MB.'); }
        try {
            $zip = new Zip($data, self::MAX_UNZIPPED);
            if (!$zip->has('xl/workbook.xml')) { throw new XlsxError('not a workbook'); }
            $text = '';
            foreach (self::textParts($zip) as $n) { $text .= $zip->read($n); }
        } catch (XlsxError $e) {
            throw ApiError::bad('This file could not be read as an Excel workbook (.xlsx).', [], 'unreadable');
        }
        $known = self::known(); $used = []; $unknown = [];
        // text of cells only (inside <t> elements), so XML markup is never mistaken for a field
        preg_match_all('#<t(?:\s[^>]*)?>([^<]*)</t>#', $text, $m);
        foreach ($m[1] as $t) {
            if (!preg_match_all(self::TOKEN, $t, $mm)) { continue; }
            foreach ($mm[1] as $name) {
                $k = self::key($name);
                if (isset($known[$k])) { $used[$known[$k]] = true; } else { $unknown[html_entity_decode($name, ENT_QUOTES | ENT_XML1, 'UTF-8')] = true; }
            }
        }
        if ($unknown) {
            throw ApiError::bad('The template has field names that the tool does not know. Fix their spelling, then upload again.',
                array_map(fn($u) => '{' . $u . '} is not a known field', array_keys($unknown)), 'unknown_fields');
        }
        if (!$used) {
            throw ApiError::bad('The template has no field to fill. Write field names in braces in the cells, for example {Facility Name} or {RTU IP-1}.', [], 'no_fields');
        }
        $order = array_flip(self::fields());
        $list = array_keys($used);
        usort($list, fn($a, $b) => $order[$a] <=> $order[$b]);
        return $list;
    }

    /** The values of one record for every field ("-" when the record has no value, e.g. RTU Internal for Honeywell). */
    public static function values(array $rec, string $today): array
    {
        $ips = (array)$rec['ips'];
        $v = ['Facility Name' => $rec['name'], 'GCP & Ring' => $rec['gcp'], 'Vendor' => $rec['vendor'], 'Date' => $rec['date'],
            'TSU PAN Engineer' => $rec['engineer'], 'Host Number' => $rec['host'] === null ? '' : (string)$rec['host'], 'Generated On' => $today];
        foreach (Engine::ALL_FIELDS as $f) { $v[$f] = $ips[$f] ?? ''; }
        foreach ($v as $k => $x) { if ((string)$x === '') { $v[$k] = '-'; } }
        return $v;
    }

    /** Fills the template for one record. Returns the .xlsx bytes. */
    public static function fill(string $template, array $values): string
    {
        $zip = new Zip($template, self::MAX_UNZIPPED);
        $parts = array_flip(self::textParts($zip));
        $known = self::known();
        $byKey = [];
        foreach ($values as $f => $x) { $byKey[self::key($f)] = $x; }
        $files = [];
        foreach ($zip->names() as $n) {
            $c = $zip->read($n);
            if (isset($parts[$n])) {
                $c = preg_replace_callback('#(<t(?:\s[^>]*)?>)([^<]*)(</t>)#', function ($m) use ($known, $byKey) {
                    $text = preg_replace_callback(self::TOKEN, function ($t) use ($known, $byKey) {
                        $k = self::key($t[1]);
                        if (!isset($known[$k])) { return $t[0]; }
                        $val = preg_replace('/[^\x{9}\x{A}\x{D}\x{20}-\x{D7FF}\x{E000}-\x{FFFD}]/u', '', (string)($byKey[$k] ?? '-')) ?? '';
                        return htmlspecialchars($val, ENT_NOQUOTES | ENT_XML1, 'UTF-8');
                    }, $m[2]);
                    return $m[1] . $text . $m[3];
                }, $c) ?? $c;
            }
            $files[$n] = $c;
        }
        return Zip::build($files);
    }

    public static function fileName(string $recordName): string
    {
        $safe = preg_replace('/[^A-Za-z0-9_\-]+/', '_', $recordName) ?: 'record';
        return 'PMT-' . $safe . '.xlsx';
    }
}
