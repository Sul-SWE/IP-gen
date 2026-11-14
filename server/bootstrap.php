<?php
declare(strict_types=1);

error_reporting(E_ALL);
ini_set('display_errors', '0');
date_default_timezone_set('UTC');   // times are taken from MySQL (the computer's clock); PHP only does arithmetic on them

if (!function_exists('array_is_list')) {   // PHP 8.0
    function array_is_list(array $a): bool { $i = 0; foreach ($a as $k => $_) { if ($k !== $i++) { return false; } } return true; }
}
// turn PHP warnings into errors so nothing fails silently (the @ operator still silences on purpose)
set_error_handler(function (int $no, string $msg, string $file, int $line): bool {
    if (!(error_reporting() & $no)) { return false; }
    throw new ErrorException($msg, 0, $no, $file, $line);
});

foreach (['pdo_mysql', 'xmlreader', 'simplexml', 'dom', 'zlib'] as $ext) {
    if (!extension_loaded($ext)) {
        http_response_code(500);
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode(['error' => 'php_extension', 'message' => "The PHP extension '$ext' is not enabled. Enable it in php.ini and restart Apache.", 'details' => []]);
        exit;
    }
}

require __DIR__ . '/Db.php';
require __DIR__ . '/Engine.php';
require __DIR__ . '/Xlsx.php';
require __DIR__ . '/Rules.php';
require __DIR__ . '/Records.php';
require __DIR__ . '/Importer.php';
require __DIR__ . '/Dashboard.php';
require __DIR__ . '/Auth.php';
require __DIR__ . '/Api.php';
