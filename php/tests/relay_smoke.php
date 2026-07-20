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
$_SERVER['HTTPS'] = 'on';
$_SERVER['HTTP_HOST'] = 'relay.example';
$_SERVER['REQUEST_URI'] = '/molgang/api/onboard/challenge';
// SQLite mirror of node_registry.sql (portable column types).
$pdo->exec('CREATE TABLE node_registry(pubkey TEXT PRIMARY KEY,address TEXT UNIQUE,device_fp TEXT,endpoint TEXT,registered REAL,last_seen REAL,region TEXT,role TEXT DEFAULT \'node\',load_hint INT DEFAULT 0,revoked INT DEFAULT 0)');
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
check('challenge scope derives from this host, not a hard-coded public relay',
    str_contains($ch['challenge'], 'knitweb-onboard:relay.example:')
    && !str_contains($ch['challenge'], '5mart.ml'));
check('onboard endpoint preserves this dapp base path',
    $ch['endpoint'] === 'https://relay.example/molgang/api/onboard/register');

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
$info = Relay::info();
check('relay info reports this host, not a hard-coded public relay', ($info['node'] ?? '') === 'relay.example');

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

// --- region-aware bootstrap roster (#98) ----------------------------------------------------
// Promote our registered node to a RELAY in eu-west via ping hints, then register a second
// relay (us-east, higher load) directly, and check the ranked roster.
$pingRelay = Relay::ping($pubHex, 'https://relay-eu.example/molgang/api/relay', 'eu-west', 'relay', 3);
check('ping accepts region/role/load bootstrap hints', !empty($pingRelay['ok']));
Db::run('INSERT INTO node_registry (pubkey,address,device_fp,endpoint,registered,last_seen,region,role,load_hint,revoked)
         VALUES (?,?,?,?,?,?,?,?,?,0)',
        [str_repeat('02', 33), 'pls1useast', 'fp', 'https://relay-us.example/molgang/api/relay',
         1.0, microtime(true), 'us-east', 'relay', 9]);

$boot = Relay::bootstrap();
check('bootstrap lists only relay-role rows, least-loaded first',
    ($boot['count'] ?? 0) === 2
    && $boot['relays'][0]['base'] === 'https://relay-eu.example/molgang/api/relay'
    && $boot['relays'][0]['region'] === 'eu-west' && $boot['relays'][0]['load'] === 3);
$bootUs = Relay::bootstrap('us-east');
check('?region= pins matching relays to the front without dropping the rest',
    ($bootUs['count'] ?? 0) === 2
    && $bootUs['relays'][0]['region'] === 'us-east'
    && $bootUs['relays'][1]['region'] === 'eu-west');
$info2 = Relay::info();
check('info() exposes the cross-region relay roster', count($info2['relays'] ?? []) === 2);

@unlink($dbfile);
echo $fail === 0 ? "\nRELAY SMOKE: PASS ✅\n" : "\nRELAY SMOKE: $fail FAILED ❌\n";
exit($fail === 0 ? 0 : 1);
