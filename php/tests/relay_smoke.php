<?php
// Relay + signed-onboarding smoke test (Refs #61 #62 #63).
// Proves the SIGNATURE GATE: a valid wallet signature onboards + relays; a missing/forged/replayed
// one is REJECTED and NEVER writes. Runs on in-process SQLite — no server, no MySQL:
//   php php/tests/relay_smoke.php
declare(strict_types=1);

require __DIR__ . '/../src/Db.php';
require __DIR__ . '/../src/Crypto.php';
require __DIR__ . '/../src/Relay.php';
require __DIR__ . '/../src/Onboard.php';

$dbfile = tempnam(sys_get_temp_dir(), 'mg_relay_') . '.sqlite';
$pdo = new PDO('sqlite:' . $dbfile);
$pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
$pdo->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);
Db::setPdo($pdo);
// SQLite mirror of node_registry.sql (portable column types).
$pdo->exec('CREATE TABLE node_registry(pubkey TEXT PRIMARY KEY,address TEXT UNIQUE,device_fp TEXT,endpoint TEXT,registered REAL,last_seen REAL,revoked INT DEFAULT 0)');
$pdo->exec('CREATE TABLE node_challenge(challenge_id TEXT PRIMARY KEY,used INT)');
$pdo->exec('CREATE TABLE relay_message(id TEXT PRIMARY KEY,from_pub TEXT,to_addr TEXT,topic TEXT,body TEXT,sig TEXT,created REAL)');

$fail = 0;
function check(string $label, bool $ok): void {
    global $fail;
    echo ($ok ? '  ok  ' : '  FAIL') . " — $label\n";
    if (!$ok) $fail++;
}

// --- a throwaway knitweb wallet (secp256k1), used to produce REAL signatures ----------------
$priv = openssl_pkey_new(['private_key_type' => OPENSSL_KEYTYPE_EC, 'curve_name' => 'secp256k1']);
if ($priv === false) { fwrite(STDERR, "secp256k1 unavailable in this PHP build — skipping\n"); exit(0); }
$d = openssl_pkey_get_details($priv);
$x = str_pad($d['ec']['x'], 32, "\0", STR_PAD_LEFT);
$y = str_pad($d['ec']['y'], 32, "\0", STR_PAD_LEFT);
$prefix = (gmp_intval(gmp_mod(gmp_init(bin2hex($y), 16), 2)) === 0) ? "\x02" : "\x03";
$pubHex = bin2hex($prefix . $x);   // 33-byte compressed, exactly what a knitweb wallet sends
function wallet_sign($priv, string $msg): string { openssl_sign($msg, $der, $priv, OPENSSL_ALGO_SHA256); return bin2hex($der); }

check('pubkey is a valid compressed secp256k1 key', Crypto::isCompressedPubkey($pubHex));
$addr = Crypto::addressFromPubkey($pubHex);
check('address derives as pls1…', str_starts_with($addr, 'pls1'));

// --- onboarding: the signature gate ---------------------------------------------------------
$ch = Onboard::challenge();
check('challenge issued with QR + endpoint', isset($ch['challenge'], $ch['qr'], $ch['endpoint']));

// (a) missing signature → REJECTED, no write
$bad = Onboard::register(['pubkey' => $pubHex, 'sig' => '', 'device_fp' => 'aa:bb:cc', 'challenge' => $ch['challenge']]);
check('register WITHOUT signature is rejected', empty($bad['ok']));
check('  …and nothing was written', Db::one('SELECT COUNT(*) c FROM node_registry')['c'] == 0);

// (b) forged signature (sign a DIFFERENT message) → REJECTED
$forged = wallet_sign($priv, $ch['challenge'] . 'tampered');
$bad2 = Onboard::register(['pubkey' => $pubHex, 'sig' => $forged, 'device_fp' => 'aa:bb:cc', 'challenge' => $ch['challenge']]);
check('register with a signature over the WRONG message is rejected', empty($bad2['ok']));

// (c) valid signature over the challenge → ACCEPTED, writes one row
$sig = wallet_sign($priv, $ch['challenge']);
$ok = Onboard::register(['pubkey' => $pubHex, 'sig' => $sig, 'device_fp' => '02:42:ac:11:00:02', 'challenge' => $ch['challenge'], 'endpoint' => 'https://node.example/knode']);
check('register with a VALID signature succeeds', !empty($ok['ok']) && $ok['address'] === $addr);
check('  …exactly one node row written', Db::one('SELECT COUNT(*) c FROM node_registry')['c'] == 1);

// (d) replay the same challenge → REJECTED (one-time use)
$replay = Onboard::register(['pubkey' => $pubHex, 'sig' => $sig, 'device_fp' => 'x', 'challenge' => $ch['challenge']]);
check('replaying a used challenge is rejected', empty($replay['ok']));

// --- relay: signed store-and-forward --------------------------------------------------------
$ping = Relay::ping($pubHex, 'https://node.example/knode');
check('registered node ping → online roster has it', !empty($ping['ok']) && count($ping['online']) === 1);

// unregistered key cannot relay
$other = openssl_pkey_new(['private_key_type' => OPENSSL_KEYTYPE_EC, 'curve_name' => 'secp256k1']);
$od = openssl_pkey_get_details($other);
$ox = str_pad($od['ec']['x'], 32, "\0", STR_PAD_LEFT);
$oy = str_pad($od['ec']['y'], 32, "\0", STR_PAD_LEFT);
$opfx = (gmp_intval(gmp_mod(gmp_init(bin2hex($oy), 16), 2)) === 0) ? "\x02" : "\x03";
$otherPub = bin2hex($opfx . $ox);
$to = '*'; $topic = 'chem'; $payload = 'CH4 is methane';
$pre = Relay::signedPreimage('', $topic, $payload);
$osig = wallet_sign($other, $pre);
$unreg = Relay::send(['from' => $otherPub, 'to' => '', 'topic' => $topic, 'body' => $payload, 'sig' => $osig]);
check('unregistered sender cannot relay', empty($unreg['ok']));

// registered + correctly-signed message → stored
$sig2 = wallet_sign($priv, $pre);
$snd = Relay::send(['from' => $pubHex, 'to' => '', 'topic' => $topic, 'body' => $payload, 'sig' => $sig2]);
check('registered node relays a SIGNED message', !empty($snd['ok']));

// tampered body (sig no longer matches) → rejected
$tamper = Relay::send(['from' => $pubHex, 'to' => '', 'topic' => $topic, 'body' => $payload . 'X', 'sig' => $sig2]);
check('relay rejects a body that does not match the signature', empty($tamper['ok']));

// fetch round-trips, and the reader can re-verify end-to-end
$got = Relay::fetch(['topic' => $topic, 'since' => 0]);
check('fetch returns the stored message', $got['count'] === 1 && $got['messages'][0]['body'] === $payload);
$m = $got['messages'][0];
$reverify = Crypto::verify($m['from'], Relay::signedPreimage((string) ($m['to'] ?? ''), $m['topic'], $m['body']), $m['sig']);
check('reader re-verifies the relayed signature end-to-end', $reverify === true);

@unlink($dbfile);
echo $fail === 0 ? "\nRELAY SMOKE: PASS ✅\n" : "\nRELAY SMOKE: $fail FAILED ❌\n";
exit($fail === 0 ? 0 : 1);
