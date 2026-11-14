<?php
// Every API request goes through this file: api/index.php/<route>
declare(strict_types=1);
require __DIR__ . '/../server/bootstrap.php';
(new Api())->handle();
