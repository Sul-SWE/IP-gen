<?php
declare(strict_types=1);

/** API error: {"error": code, "message": text, "details": [...]} with an HTTP status. */
final class ApiError extends Exception
{
    public int $status; public string $errCode; public array $details; public array $extra;

    public function __construct(int $status, string $code, string $message, array $details = [], array $extra = [])
    {
        parent::__construct($message);
        $this->status = $status; $this->errCode = $code; $this->details = $details; $this->extra = $extra;
    }

    public function body(): array
    {
        return array_merge(['error' => $this->errCode, 'message' => $this->getMessage(), 'details' => $this->details], $this->extra);
    }

    public static function bad(string $m, array $d = [], string $c = 'invalid'): self { return new self(400, $c, $m, $d); }
    public static function conflict(string $m, array $d = [], string $c = 'conflict', array $x = []): self { return new self(409, $c, $m, $d, $x); }
    public static function notFound(string $m = 'Not found.'): self { return new self(404, 'not_found', $m); }
}

/** Thin PDO wrapper. All writes run in one transaction that first takes the global write lock. */
final class Db
{
    public PDO $pdo;
    private ?string $now = null;

    public function __construct(array $c, bool $selectDb = true)
    {
        $dsn = 'mysql:host=' . $c['host'] . ';port=' . (int)$c['port'] . ($selectDb ? ';dbname=' . $c['name'] : '') . ';charset=utf8mb4';
        $this->pdo = new PDO($dsn, $c['user'], $c['pass'], [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
            PDO::ATTR_EMULATE_PREPARES => false,
            PDO::ATTR_TIMEOUT => 5,
        ]);
        // after taking the write lock, every statement sees the newest committed data
        $this->pdo->exec('SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED');
    }

    public function q(string $sql, array $params = []): PDOStatement
    {
        $st = $this->pdo->prepare($sql);
        $st->execute(array_values($params) === $params ? $params : $params);
        return $st;
    }
    public function all(string $sql, array $p = []): array { return $this->q($sql, $p)->fetchAll(); }
    public function one(string $sql, array $p = []): ?array { $r = $this->q($sql, $p)->fetch(); return $r === false ? null : $r; }
    public function value(string $sql, array $p = []) { $r = $this->q($sql, $p)->fetchColumn(); return $r === false ? null : $r; }
    public function insert(string $sql, array $p = []): int { $this->q($sql, $p); return (int)$this->pdo->lastInsertId(); }

    /** Server time of the database (= the clock of the computer running MySQL), 'Y-m-d H:i:s'. */
    public function now(): string
    {
        if ($this->now === null) { $this->now = (string)$this->value('SELECT DATE_FORMAT(NOW(), \'%Y-%m-%d %H:%i:%s\')'); }
        return $this->now;
    }
    public function today(): string { return substr($this->now(), 0, 10); }
    public function resetClock(): void { $this->now = null; }

    public function begin(): void { if (!$this->pdo->inTransaction()) { $this->pdo->beginTransaction(); } }
    public function commit(): void { if ($this->pdo->inTransaction()) { $this->pdo->commit(); } }
    public function rollback(): void { if ($this->pdo->inTransaction()) { $this->pdo->rollBack(); } }

    /** Serialise all writers: every state-changing request takes this row lock first. */
    public function lockWrites(): void
    {
        $this->begin();
        $this->q("SELECT value FROM settings WHERE name = 'write_lock' FOR UPDATE")->fetchAll();
    }

    /** Run fn inside one transaction (with the write lock); roll back on any error. */
    public function write(callable $fn)
    {
        $this->lockWrites();
        try {
            $out = $fn($this);
            $this->commit();
            return $out;
        } catch (Throwable $e) {
            $this->rollback();
            throw $e;
        }
    }

    public static function isDuplicate(Throwable $e): bool
    {
        return $e instanceof PDOException && ($e->getCode() === '23000' || (isset($e->errorInfo[1]) && (int)$e->errorInfo[1] === 1062));
    }
}

function fmt_dt($v): string { return $v ? substr((string)$v, 0, 16) : ''; }
function jdec($s): array { $v = json_decode((string)$s, true); return is_array($v) ? $v : []; }
function jenc($v): string { return json_encode($v, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES); }
