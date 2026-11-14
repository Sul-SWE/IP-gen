<?php
// Runs engine functions on a JSON job (stdin) and prints JSON results. Used to compare with the reference implementation.
declare(strict_types=1);
require __DIR__ . '/../server/Engine.php';
$job = json_decode(stream_get_contents(STDIN), true);
$out = [];
foreach ($job['builds'] as [$block, $n]) { $out['builds'][] = Engine::build($block, $n); }
foreach ($job['rules'] as [$rule, $octets]) { $out['rules'][] = Engine::validateRule($rule, $octets); }
foreach ($job['imports'] as [$rows, $existing, $cfg]) {
    $idx = Engine::newIndex();
    foreach ($existing as $e) { Engine::indexAdd($idx, $e['name'], $e['ips'], $e['where']); }
    $out['imports'][] = Engine::checkImportRows($rows, $idx, $cfg);
}
foreach ($job['misc'] as [$fn, $arg]) { $out['misc'][] = Engine::$fn(...$arg); }
echo json_encode($out);
