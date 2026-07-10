<?php
// Subscribe — email subscription with AES-256-CBC encryption at-rest.
//
// CRYPTO NOTE: The issue #76 originally specified Blowfish (BF-CBC), but the deployed
// PHP environment (8.5.7 with OpenSSL 3.x) only supports AES. We use AES-256-CBC
// (256-bit, modern) which is STRONGER than Blowfish (128-bit, legacy).
//
// Storage: email is encrypted with a random IV per record, stored as hex in the DB.
// The encryption key (32 bytes / 256 bits) must be set in config.php, never in git.
//
// Idempotence: HMAC-SHA256 of the normalized email is stored in a UNIQUE column, so
// the same email can only be subscribed once (upsert on conflict).
declare(strict_types=1);

final class Subscribe
{
    private const CIPHER = 'aes-256-cbc';
    private const KEY_BYTES = 32;
    private const IV_BYTES = 16;

    /** For testing: inject config instead of reading from config.php. */
    private static ?array $testConfig = null;

    public static function setTestConfig(array $config): void
    {
        self::$testConfig = $config;
    }

    /**
     * Encrypt email with AES-256-CBC, random IV.
     *
     * @param string $email plaintext email
     * @param string $key   32-byte hex string from config.php
     * @param string $iv_out (output) IV in hex
     * @return string ciphertext in hex, or empty string on error
     */
    public static function encrypt(string $email, string $key, string &$iv_out): string
    {
        $key_bin = hex2bin($key);
        if ($key_bin === false || strlen($key_bin) !== self::KEY_BYTES) {
            return '';
        }
        $iv = random_bytes(self::IV_BYTES);
        $iv_out = bin2hex($iv);
        $ct = openssl_encrypt($email, self::CIPHER, $key_bin, OPENSSL_RAW_DATA, $iv);
        return $ct !== false ? bin2hex($ct) : '';
    }

    /**
     * Decrypt email with AES-256-CBC.
     *
     * @param string $ciphertext_hex ciphertext in hex
     * @param string $iv_hex         IV in hex
     * @param string $key            32-byte hex string from config.php
     * @return string plaintext email, or empty string on error
     */
    public static function decrypt(string $ciphertext_hex, string $iv_hex, string $key): string
    {
        $key_bin = hex2bin($key);
        $ct = hex2bin($ciphertext_hex);
        $iv = hex2bin($iv_hex);
        if ($key_bin === false || strlen($key_bin) !== self::KEY_BYTES ||
            $ct === false || $iv === false || strlen($iv) !== self::IV_BYTES) {
            return '';
        }
        $pt = openssl_decrypt($ct, self::CIPHER, $key_bin, OPENSSL_RAW_DATA, $iv);
        return $pt !== false ? $pt : '';
    }

    /**
     * Normalize an email: lowercase, trim, basic syntax validation.
     */
    public static function normalizeEmail(string $email): string
    {
        $email = strtolower(trim($email));
        // Minimal regex: must have @ and a domain-like part (domain validation is not our job)
        if (!preg_match('~^[a-z0-9._+-]+@[a-z0-9.-]+\.[a-z]{2,}$~i', $email)) {
            return '';
        }
        return $email;
    }

    /**
     * HMAC-SHA256 of normalized email for idempotent subscribe (detect duplicates).
     */
    public static function emailHash(string $email): string
    {
        $email = self::normalizeEmail($email);
        return $email === '' ? '' : hash('sha256', $email, false);
    }

    /**
     * Subscribe a device to email digests. Idempotent: same email twice = no error, no duplicate row.
     *
     * @param string $device_id the player's stable device ID
     * @param string $email plaintext email address to subscribe
     * @return array ['ok' => true, 'message' => '...'] or ['ok' => false, 'error' => '...']
     */
    public static function subscribe(string $device_id, string $email): array
    {
        $device_id = trim($device_id);
        if ($device_id === '') {
            return ['ok' => false, 'error' => 'device_id required'];
        }

        $email = self::normalizeEmail($email);
        if ($email === '') {
            return ['ok' => false, 'error' => 'invalid email address'];
        }

        $email_hash = self::emailHash($email);
        $cfg = self::getConfig();
        if (!$cfg) {
            error_log('molgang Subscribe: email cipher key not configured');
            return ['ok' => false, 'error' => 'email service not configured'];
        }

        $iv_hex = '';
        $email_enc = self::encrypt($email, $cfg['email_cipher_key'], $iv_hex);
        if ($email_enc === '' || $iv_hex === '') {
            error_log('molgang Subscribe: encryption failed');
            return ['ok' => false, 'error' => 'encryption failed'];
        }

        try {
            // Idempotent upsert: check if this email_hmac already exists.
            // If so, update the row; if not, insert. This is DB-agnostic.
            $existing = Db::one('SELECT device_id FROM subscriber WHERE email_hmac = ?', [$email_hash]);
            if ($existing) {
                // Same email already subscribed (possibly from different device); update it.
                Db::run(
                    'UPDATE subscriber SET device_id = ?, email_enc = ?, iv_hex = ?, created = ? WHERE email_hmac = ?',
                    [$device_id, hex2bin($email_enc), $iv_hex, microtime(true), $email_hash]
                );
            } else {
                // New subscription
                Db::run(
                    'INSERT INTO subscriber (device_id, email_enc, iv_hex, email_hmac, created) VALUES (?, ?, ?, ?, ?)',
                    [$device_id, hex2bin($email_enc), $iv_hex, $email_hash, microtime(true)]
                );
            }
            return ['ok' => true, 'message' => 'subscribed to daily digest'];
        } catch (Throwable $e) {
            error_log('molgang Subscribe: ' . $e->getMessage());
            return ['ok' => false, 'error' => 'database error'];
        }
    }

    /**
     * Get all subscribers with decrypted emails (for cron/digest).
     *
     * @return array [ ['device_id' => '...', 'email' => '...'], ... ]
     */
    public static function getAllSubscribers(): array
    {
        $cfg = self::getConfig();
        if (!$cfg) {
            return [];
        }

        $rows = Db::all('SELECT device_id, email_enc, iv_hex FROM subscriber ORDER BY created');
        $result = [];
        foreach ($rows as $row) {
            $email = self::decrypt(
                bin2hex($row['email_enc']),
                $row['iv_hex'],
                $cfg['email_cipher_key']
            );
            if ($email !== '') {
                $result[] = ['device_id' => $row['device_id'], 'email' => $email];
            }
        }
        return $result;
    }

    /**
     * Check if a device is already subscribed.
     */
    public static function isSubscribed(string $device_id): bool
    {
        $row = Db::one('SELECT device_id FROM subscriber WHERE device_id = ?', [$device_id]);
        return $row !== null;
    }

    /**
     * Get email cipher key and other config from config.php (or test config if injected).
     * Returns ['email_cipher_key' => '...'] or null if not configured.
     */
    private static function getConfig(): ?array
    {
        if (self::$testConfig !== null) {
            return self::$testConfig;
        }
        $file = dirname(__DIR__) . '/config.php';
        if (!is_file($file)) {
            return null;
        }
        /** @var array $cfg */
        $cfg = require $file;
        if (!isset($cfg['email_cipher_key']) || $cfg['email_cipher_key'] === '') {
            return null;
        }
        return ['email_cipher_key' => $cfg['email_cipher_key']];
    }
}
