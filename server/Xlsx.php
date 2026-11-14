<?php
/**
 * Minimal .xlsx reader and writer in plain PHP (needs only the zlib and XMLReader extensions,
 * which are always on in XAMPP). No external library.
 */

declare(strict_types=1);

final class XlsxError extends Exception {}

/* ------------------------------------------------------------ ZIP container */
final class Zip
{
    private string $data;
    private array $entries = []; // name => [method, csize, usize, offset]

    public function __construct(string $data, int $maxUnzipped)
    {
        $this->data = $data;
        $len = strlen($data);
        if ($len < 22 || substr($data, 0, 2) !== 'PK') { throw new XlsxError('not a zip'); }
        $eocd = strrpos($data, "PK\x05\x06");
        if ($eocd === false || $eocd + 22 > $len) { throw new XlsxError('no central directory'); }
        $e = unpack('vdisk/vcdisk/vcount/vtotal/Vsize/Voffset', substr($data, $eocd + 4, 16));
        $pos = $e['offset']; $total = 0;
        for ($i = 0; $i < $e['total']; $i++) {
            if ($pos + 46 > $len || substr($data, $pos, 4) !== "PK\x01\x02") { throw new XlsxError('bad central directory'); }
            $h = unpack('vver/vneed/vflag/vmethod/vtime/vdate/Vcrc/Vcsize/Vusize/vnlen/vxlen/vclen/vdisk/viattr/Vxattr/Voffset', substr($data, $pos + 4, 42));
            $name = substr($data, $pos + 46, $h['nlen']);
            $total += $h['usize'];
            if ($total > $maxUnzipped) { throw new XlsxError('too large unpacked'); }
            $this->entries[$name] = [$h['method'], $h['csize'], $h['usize'], $h['offset']];
            $pos += 46 + $h['nlen'] + $h['xlen'] + $h['clen'];
        }
    }

    public function has(string $name): bool { return isset($this->entries[$name]); }

    public function read(string $name): string
    {
        if (!isset($this->entries[$name])) { throw new XlsxError("missing $name"); }
        [$method, $csize, $usize, $off] = $this->entries[$name];
        if (substr($this->data, $off, 4) !== "PK\x03\x04") { throw new XlsxError('bad local header'); }
        $l = unpack('vnlen/vxlen', substr($this->data, $off + 26, 4));
        $raw = substr($this->data, $off + 30 + $l['nlen'] + $l['xlen'], $csize);
        if ($method === 0) { return $raw; }
        if ($method !== 8) { throw new XlsxError('unsupported compression'); }
        $out = @gzinflate($raw, max(1, $usize));
        if ($out === false) { throw new XlsxError('corrupt data'); }
        return $out;
    }

    /** Build a zip file from [name => content]. */
    public static function build(array $files): string
    {
        $out = ''; $central = ''; $n = 0;
        [$dtime, $ddate] = [0, (2026 - 1980) << 9 | 1 << 5 | 1];
        foreach ($files as $name => $content) {
            $crc = crc32($content);
            $comp = gzdeflate($content, 6);
            $off = strlen($out);
            $out .= "PK\x03\x04" . pack('vvvvvVVVvv', 20, 0x0800, 8, $dtime, $ddate, $crc, strlen($comp), strlen($content), strlen($name), 0) . $name . $comp;
            $central .= "PK\x01\x02" . pack('vvvvvvVVVvvvvvVV', 20, 20, 0x0800, 8, $dtime, $ddate, $crc, strlen($comp), strlen($content), strlen($name), 0, 0, 0, 0, 0, $off) . $name;
            $n++;
        }
        return $out . $central . "PK\x05\x06" . pack('vvvvVVv', 0, 0, $n, $n, strlen($central), strlen($out), 0);
    }
}

/* ------------------------------------------------------------ reader */
final class XlsxReader
{
    private Zip $zip;
    private array $shared = [];
    private array $dateStyles = [];

    public function __construct(string $data, int $maxUnzipped)
    {
        $this->zip = new Zip($data, $maxUnzipped);
        if (!$this->zip->has('xl/workbook.xml')) { throw new XlsxError('not a workbook'); }
        if ($this->zip->has('xl/sharedStrings.xml')) { $this->loadShared($this->zip->read('xl/sharedStrings.xml')); }
        if ($this->zip->has('xl/styles.xml')) { $this->loadStyles($this->zip->read('xl/styles.xml')); }
    }

    private static function xml(string $s): SimpleXMLElement
    {
        $x = @simplexml_load_string($s, 'SimpleXMLElement', LIBXML_NONET | LIBXML_COMPACT);
        if ($x === false) { throw new XlsxError('bad xml'); }
        return $x;
    }

    /** Text of a <si>/<is> element: all <t> runs, but not the phonetic <rPh> runs. */
    private static function richText(DOMNode $node): string
    {
        $s = '';
        foreach ($node->childNodes as $c) {
            if ($c->localName === 't') { $s .= $c->textContent; }
            elseif ($c->localName === 'r') { foreach ($c->childNodes as $t) { if ($t->localName === 't') { $s .= $t->textContent; } } }
        }
        return $s;
    }

    private function loadShared(string $xml): void
    {
        $r = new XMLReader();
        $r->XML($xml, null, LIBXML_NONET | LIBXML_COMPACT);
        while (@$r->read()) {
            if ($r->nodeType === XMLReader::ELEMENT && $r->localName === 'si') {
                $n = $r->expand();
                $this->shared[] = $n ? self::richText($n) : '';
            }
        }
        $r->close();
    }

    private function loadStyles(string $xml): void
    {
        $x = self::xml($xml);
        $x->registerXPathNamespace('m', 'http://schemas.openxmlformats.org/spreadsheetml/2006/main');
        $custom = [];
        foreach ($x->xpath('//m:numFmts/m:numFmt') ?: [] as $f) { $custom[(int)$f['numFmtId']] = (string)$f['formatCode']; }
        $i = 0;
        foreach ($x->xpath('//m:cellXfs/m:xf') ?: [] as $xf) {
            $id = (int)$xf['numFmtId'];
            if (($id >= 14 && $id <= 22) || ($id >= 45 && $id <= 47) || (isset($custom[$id]) && self::isDateFormat($custom[$id]))) { $this->dateStyles[$i] = true; }
            $i++;
        }
    }

    private static function isDateFormat(string $code): bool
    {
        $c = preg_replace(['/"[^"]*"/', '/\\\\./', '/\[[^\]]*\]/'], '', $code) ?? '';
        $c = explode(';', $c)[0];
        return strcasecmp(trim($c), 'General') !== 0 && (bool)preg_match('/[dmyhs]/i', $c);
    }

    /** Sheets in workbook order: [[title, path], ...]. */
    public function sheets(): array
    {
        $rels = [];
        if ($this->zip->has('xl/_rels/workbook.xml.rels')) {
            $x = self::xml($this->zip->read('xl/_rels/workbook.xml.rels'));
            foreach ($x->children() as $rel) {
                $t = (string)$rel['Target'];
                $t = str_starts_with($t, '/') ? ltrim($t, '/') : 'xl/' . $t;
                $rels[(string)$rel['Id']] = preg_replace('#/[^/]+/\.\./#', '/', $t);
            }
        }
        $wb = self::xml($this->zip->read('xl/workbook.xml'));
        $out = [];
        foreach ($wb->children('http://schemas.openxmlformats.org/spreadsheetml/2006/main')->sheets->sheet ?? [] as $s) {
            $rid = (string)$s->attributes('http://schemas.openxmlformats.org/officeDocument/2006/relationships')['id'];
            if (isset($rels[$rid]) && $this->zip->has($rels[$rid])) { $out[] = [(string)$s->attributes()['name'], $rels[$rid]]; }
        }
        return $out;
    }

    private static function colIndex(string $ref): int
    {
        $n = 0;
        for ($i = 0, $l = strlen($ref); $i < $l; $i++) {
            $ch = ord($ref[$i]);
            if ($ch < 65 || $ch > 90) { break; }
            $n = $n * 26 + ($ch - 64);
        }
        return $n - 1;
    }

    /**
     * Calls $fn(int rowNumber, array cells [colIndex => value]) for every row of the sheet, in order.
     * Values: string, int, float, bool, or 'YYYY-MM-DD' for date-formatted numbers. $fn returns false to stop.
     */
    public function rows(string $path, callable $fn): void
    {
        $r = new XMLReader();
        $r->XML($this->zip->read($path), null, LIBXML_NONET | LIBXML_COMPACT | LIBXML_PARSEHUGE);
        $rowNo = 0;
        while (@$r->read() && !($r->nodeType === XMLReader::ELEMENT && $r->localName === 'row')) { }
        while ($r->nodeType === XMLReader::ELEMENT && $r->localName === 'row') {
            $rowNo = $r->getAttribute('r') !== null ? (int)$r->getAttribute('r') : $rowNo + 1;
            $node = $r->expand();
            $cells = []; $col = -1;
            if ($node) {
                foreach ($node->childNodes as $c) {
                    if ($c->localName !== 'c') { continue; }
                    $ref = $c->getAttribute('r');
                    $col = $ref !== '' ? self::colIndex($ref) : $col + 1;
                    $cells[$col] = $this->cellValue($c);
                }
            }
            if ($fn($rowNo, $cells) === false) { break; }
            if (!@$r->next('row')) { break; }
        }
        $r->close();
    }

    private function cellValue(DOMElement $c)
    {
        $t = $c->getAttribute('t');
        $v = null; $is = null;
        foreach ($c->childNodes as $ch) {
            if ($ch->localName === 'v') { $v = $ch->textContent; }
            elseif ($ch->localName === 'is') { $is = $ch; }
        }
        if ($t === 'inlineStr') { return $is ? self::richText($is) : ''; }
        if ($v === null) { return null; }
        switch ($t) {
            case 's': return $this->shared[(int)$v] ?? '';
            case 'str': case 'e': return $v;
            case 'b': return $v === '1';
        }
        if (!is_numeric($v)) { return $v; }
        $num = preg_match('/^-?\d+$/', $v) && strlen($v) < 16 ? (int)$v : (float)$v;
        $s = $c->getAttribute('s');
        if ($s !== '' && isset($this->dateStyles[(int)$s]) && $num >= 1 && $num < 2958466) {
            return gmdate('Y-m-d', ((int)floor((float)$num) - 25569) * 86400);
        }
        return $num;
    }
}

/* ------------------------------------------------------------ writer */
final class XlsxWriter
{
    private static function x(string $s): string
    {
        $s = preg_replace('/[^\x{9}\x{A}\x{D}\x{20}-\x{D7FF}\x{E000}-\x{FFFD}\x{10000}-\x{10FFFF}]/u', '', $s) ?? '';
        return htmlspecialchars($s, ENT_QUOTES | ENT_XML1, 'UTF-8');
    }

    private static function colName(int $i): string
    {
        $s = '';
        for ($i++; $i > 0; $i = intdiv($i - 1, 26)) { $s = chr(65 + ($i - 1) % 26) . $s; }
        return $s;
    }

    /** One sheet: header row (bold, frozen, auto-filter) + rows. Every cell is written as text, never as a formula. */
    public static function build(string $sheetName, array $header, array $rows, array $widths): string
    {
        $last = self::colName(count($header) - 1);
        $n = count($rows) + 1;
        $sd = '';
        foreach (array_merge([$header], $rows) as $ri => $row) {
            $r = $ri + 1;
            $sd .= '<row r="' . $r . '">';
            foreach (array_values($row) as $ci => $val) {
                $sd .= '<c r="' . self::colName($ci) . $r . '" t="inlineStr"' . ($ri === 0 ? ' s="1"' : '') . '><is><t xml:space="preserve">' . self::x((string)$val) . '</t></is></c>';
            }
            $sd .= '</row>';
        }
        $cols = '';
        foreach ($widths as $i => $w) { $cols .= '<col min="' . ($i + 1) . '" max="' . ($i + 1) . '" width="' . $w . '" customWidth="1"/>'; }
        $ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"';
        $sheet = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' . "\n<worksheet $ns>"
            . '<dimension ref="A1:' . $last . $n . '"/>'
            . '<sheetViews><sheetView workbookViewId="0"><pane xSplit="1" ySplit="1" topLeftCell="B2" activePane="bottomRight" state="frozen"/></sheetView></sheetViews>'
            . '<sheetFormatPr defaultRowHeight="15"/><cols>' . $cols . '</cols><sheetData>' . $sd . '</sheetData>'
            . '<autoFilter ref="A1:' . $last . $n . '"/></worksheet>';
        $name = self::x($sheetName);
        $wb = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' . "\n<workbook $ns><sheets><sheet name=\"$name\" sheetId=\"1\" r:id=\"rId1\"/></sheets>"
            . "<definedNames><definedName name=\"_xlnm._FilterDatabase\" localSheetId=\"0\" hidden=\"1\">'$name'!\$A\$1:\$$last\$$n</definedName></definedNames></workbook>";
        $styles = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' . "\n"
            . '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            . '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
            . '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
            . '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            . '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            . '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
            . '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>';
        return Zip::build([
            '[Content_Types].xml' => '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' . "\n"
                . '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                . '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
                . '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                . '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                . '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>',
            '_rels/.rels' => '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' . "\n"
                . '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
            'xl/workbook.xml' => $wb,
            'xl/_rels/workbook.xml.rels' => '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' . "\n"
                . '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                . '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                . '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
            'xl/worksheets/sheet1.xml' => $sheet,
            'xl/styles.xml' => $styles,
        ]);
    }
}
