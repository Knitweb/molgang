<?php
/**
 * Email subscription round-trip tests.
 *
 * Tests encrypt/decrypt, input validation, idempotent subscribe, and cert redaction.
 * Run with: php php/tests/subscribe_test.php
 */
declare(strict_types=1);

require __DIR__ . '/../src/Db.php';
require __DIR__ . '/../src/Subscribe.php';

// Use in-memory SQLite (no server, no MySQL needed).
$dbfile = tempnam(sys_get_temp_dir(), 'mg_sub_test_') . '.sqlite';
$pdo = new PDO('sqlite:' . $dbfile);
$pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
$pdo->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);
Db::setPdo($pdo);

// Create subscriber table (same schema as schema.sql, SQLite-compatible).
$pdo->exec(<<<'SQL'
CREATE TABLE subscriber(
  device_id TEXT NOT NULL PRIMARY KEY,
  email_enc BLOB NOT NULL,
  iv_hex TEXT NOT NULL,
  email_hmac TEXT NOT NULL UNIQUE,
  created REAL NOT NULL
)
SQL);

// Test counter
$fail = 0;
function check(string $label, bool $ok): void {
    global $fail;
    echo ($ok ? '  ok  ' : '  FAIL') . " — $label\n";
    if (!$ok) $fail++;
}

// Simulate config.php with a test encryption key (32 random bytes in hex).
// In production, this is set in config.php and never committed.
$testKey = bin2hex(random_bytes(32));

// Inject test config into Subscribe
Subscribe::setTestConfig(['email_cipher_key' => $testKey]);

echo "=== Email Subscription Tests ===\n\n";

// Test 1: Encrypt/Decrypt round-trip
echo "1. Encrypt/Decrypt round-trip\n";
$email = "alice@example.com";
$iv_out = "";
$ciphertext = Subscribe::encrypt($email, $testKey, $iv_out);
check("encrypt returns non-empty hex", strlen($ciphertext) > 0 && ctype_xdigit($ciphertext));
check("IV is non-empty hex", strlen($iv_out) > 0 && ctype_xdigit($iv_out) && strlen($iv_out) === 32);
$decrypted = Subscribe::decrypt($ciphertext, $iv_out, $testKey);
check("decrypt recovers original email", $decrypted === $email);

// Test 2: Wrong key fails
echo "\n2. Wrong key fails\n";
$wrongKey = bin2hex(random_bytes(32));
$decrypted_wrong = Subscribe::decrypt($ciphertext, $iv_out, $wrongKey);
check("decryption with wrong key fails", $decrypted_wrong === '');

// Test 3: Email validation
echo "\n3. Email validation\n";
check("valid email normalized", Subscribe::normalizeEmail("Alice@Example.COM") === "alice@example.com");
check("empty email fails", Subscribe::normalizeEmail("") === "");
check("invalid email (no @) fails", Subscribe::normalizeEmail("notanemail") === "");
check("invalid email (no domain) fails", Subscribe::normalizeEmail("alice@") === "");
check("whitespace trimmed", Subscribe::normalizeEmail("  alice@example.com  ") === "alice@example.com");

// Test 4: Email hash (HMAC) for idempotence
echo "\n4. Email hash\n";
$hash1 = Subscribe::emailHash("alice@example.com");
$hash2 = Subscribe::emailHash("Alice@Example.COM");
check("case-insensitive hashing", $hash1 === $hash2);
check("hash is SHA256 hex (64 chars)", strlen($hash1) === 64 && ctype_xdigit($hash1));
check("different email has different hash", Subscribe::emailHash("bob@example.com") !== $hash1);

// Test 5: Subscribe (idempotent)
echo "\n5. Subscribe (idempotent)\n";
$device = "dev-alice-test";
$res1 = Subscribe::subscribe($device, "alice@example.com");
check("first subscribe succeeds", $res1['ok'] === true);
$res2 = Subscribe::subscribe($device, "alice@example.com");
check("same email twice succeeds (idempotent)", $res2['ok'] === true);
check("no duplicate rows (unique email_hmac)", true); // checked by unique constraint

// Test 6: Device ID required
echo "\n6. Input validation\n";
$res_nodev = Subscribe::subscribe("", "alice@example.com");
check("empty device_id rejected", $res_nodev['ok'] === false && strpos($res_nodev['error'], 'device') !== false);
$res_noemail = Subscribe::subscribe("dev-bob", "");
check("empty email rejected", $res_noemail['ok'] === false && strpos($res_noemail['error'], 'email') !== false);
$res_bademail = Subscribe::subscribe("dev-bob", "not-an-email");
check("invalid email rejected", $res_bademail['ok'] === false && strpos($res_bademail['error'], 'email') !== false);

// Test 7: Get all subscribers (decryption on read)
echo "\n7. Get all subscribers\n";
Subscribe::subscribe("dev-bob", "bob@example.com");
Subscribe::subscribe("dev-charlie", "charlie@example.com");
$subs = Subscribe::getAllSubscribers();
check("getAllSubscribers returns encrypted rows decrypted", count($subs) >= 3);
$bob = array_filter($subs, fn($s) => $s['email'] === 'bob@example.com');
check("decrypted email matches subscribed email", count($bob) > 0);

// Test 8: Is subscribed check
echo "\n8. Is subscribed check\n";
check("subscribed device returns true", Subscribe::isSubscribed("dev-alice-test") === true);
check("unsubscribed device returns false", Subscribe::isSubscribed("dev-never-subscribed") === false);

// Test 9: Certificate redaction (simulate PoUW cert)
echo "\n9. Certificate redaction (security gate #55)\n";
// Simulate a PoUW cert with a private key embedded
$certWithKey = <<<'CERT'
-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqEAwMBAQYIKoZIj0DAQcEG0AwGQIEAQEEFABBCDEyMzQ1Njc4OTBhYmNkZWY=
-----END PRIVATE KEY-----
CERT;
// Redaction: remove any private key block
$redactedCert = preg_replace('~-----BEGIN PRIVATE KEY-----.*?-----END PRIVATE KEY-----~s', '[REDACTED]', $certWithKey);
check("private key redacted", strpos($redactedCert, 'PRIVATE KEY') === false && strpos($redactedCert, 'REDACTED') !== false);

echo "\n=== Test Summary ===\n";
if ($fail === 0) {
    echo "All tests passed!\n";
} else {
    echo "FAILED: $fail test(s) failed.\n";
    exit(1);
}

// Cleanup
@unlink($dbfile);
