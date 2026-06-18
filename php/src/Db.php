<?php
// Db — a thin PDO/MySQL wrapper. Reads credentials from config.php (NEVER committed).
declare(strict_types=1);

final class Db
{
    private static ?PDO $pdo = null;

    /** Inject a PDO (tests / alternate drivers). */
    public static function setPdo(PDO $pdo): void
    {
        self::$pdo = $pdo;
    }

    public static function pdo(): PDO
    {
        if (self::$pdo instanceof PDO) {
            return self::$pdo;
        }
        $cfg = self::config();
        $dsn = sprintf('mysql:host=%s;dbname=%s;charset=utf8mb4', $cfg['host'], $cfg['name']);
        self::$pdo = new PDO($dsn, $cfg['user'], $cfg['pass'], [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
            PDO::ATTR_EMULATE_PREPARES => false,
        ]);
        return self::$pdo;
    }

    /** Load DB config from config.php (host/name/user/pass), or environment fallbacks. */
    private static function config(): array
    {
        $file = dirname(__DIR__) . '/config.php';
        if (is_file($file)) {
            /** @var array $config */
            $config = require $file;
            return $config;
        }
        return [
            'host' => getenv('MOLGANG_DB_HOST') ?: 'localhost',
            'name' => getenv('MOLGANG_DB_NAME') ?: '',
            'user' => getenv('MOLGANG_DB_USER') ?: '',
            'pass' => getenv('MOLGANG_DB_PASS') ?: '',
        ];
    }

    /** @return array<int,array<string,mixed>> */
    public static function all(string $sql, array $args = []): array
    {
        $st = self::pdo()->prepare($sql);
        $st->execute($args);
        return $st->fetchAll();
    }

    public static function one(string $sql, array $args = []): ?array
    {
        $st = self::pdo()->prepare($sql);
        $st->execute($args);
        $row = $st->fetch();
        return $row === false ? null : $row;
    }

    public static function run(string $sql, array $args = []): void
    {
        self::pdo()->prepare($sql)->execute($args);
    }
}
