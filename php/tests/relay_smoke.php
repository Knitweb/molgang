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

// --- fleet telemetry: the 1M/GTA6 scoreboard (#131), keyed to docs/MEASUREMENT.md -----------
$tel = Relay::telemetry();
check('telemetry counts the live+active peer (presence ∧ real work in-window)',
    ($tel['peers_online'] ?? 0) === 1);
check('telemetry exposes the MEASUREMENT.md metric names + GTA6 reference',
    isset($tel['knits_per_sec'], $tel['useful_work_per_sec'])
    && ($tel['gta6_reference_peers'] ?? 0) === 1_000_000
    && ($tel['scope'] ?? '') === 'relay');
check('telemetry exposes the deduped concurrent-pubkey SET for fleet union (#131)',
    isset($tel['peer_pubkeys']) && is_array($tel['peer_pubkeys'])
    && count($tel['peer_pubkeys']) === 1 && $tel['peer_pubkeys'][0] === $pubHex);

// presence WITHOUT work in-window must NOT count (activity floor, rule 3): age out the message
Db::run('UPDATE relay_message SET created = ?', [microtime(true) - (Relay::ONLINE_WINDOW_S + 60)]);
$tel2 = Relay::telemetry();
check('a peer with stale (out-of-window) work drops from the concurrent count',
    ($tel2['peers_online'] ?? -1) === 0 && ($tel2['useful_work_per_sec'] ?? -1) === 0.0);

// --- anti-entropy: reconcile with a peer relay (#96) ----------------------------------------
// A fake PEER relay served through the injectable $http: honours ?since= exactly like fetch().
$peerPayload = 'NaCl is table salt';
$peerPre = Relay::signedPreimage('', $topic, $peerPayload);
$peerSig = wallet_sign($priv, $peerPre);                       // signed by our REGISTERED node
$peerMsg = ['id' => bin2hex(random_bytes(12)), 'from' => $pubHex, 'to' => null,
            'topic' => $topic, 'body' => $peerPayload, 'sig' => $peerSig, 'created' => 100.0];
$forgedMsg = ['id' => bin2hex(random_bytes(12)), 'from' => $pubHex, 'to' => null,
              'topic' => $topic, 'body' => $peerPayload . ' FORGED', 'sig' => $peerSig,
              'created' => 101.0];
$strangerMsg = ['id' => bin2hex(random_bytes(12)), 'from' => $otherPub, 'to' => null,
                'topic' => $topic, 'body' => $payload, 'sig' => $osig, 'created' => 102.0];
$peerLog = [$peerMsg, $forgedMsg, $strangerMsg];
$peerCalls = [];
$fakeHttp = function (string $url) use ($peerLog, &$peerCalls): array {
    $peerCalls[] = $url;
    parse_str((string) parse_url($url, PHP_URL_QUERY), $q);
    $since = (float) ($q['since'] ?? 0);
    $out = array_values(array_filter($peerLog, fn ($m) => $m['created'] > $since));
    $cursor = $since;
    foreach ($out as $m) $cursor = max($cursor, $m['created']);
    return ['messages' => $out, 'cursor' => $cursor, 'count' => count($out)];
};

$before = (int) Db::one('SELECT COUNT(*) c FROM relay_message')['c'];
$rec = Relay::reconcile(['https://peer.example/molgang/api/relay'], $fakeHttp);
$p0 = $rec['peers'][0] ?? [];
check('reconcile pass reaches the peer and reports per-peer stats', !empty($rec['ok']) && !empty($p0['ok']));
check('a message stored only on the peer propagates here', ($p0['new'] ?? 0) === 1
    && Db::one('SELECT 1 x FROM relay_message WHERE id=?', [$peerMsg['id']]) !== null);
check('a forged peer message is refused on ingest (send() gate)', ($p0['rejected'] ?? 0) === 2
    && Db::one('SELECT 1 x FROM relay_message WHERE id=?', [$forgedMsg['id']]) === null);
check('an unregistered peer sender is refused on ingest',
    Db::one('SELECT 1 x FROM relay_message WHERE id=?', [$strangerMsg['id']]) === null);
$after = (int) Db::one('SELECT COUNT(*) c FROM relay_message')['c'];
check('exactly one new row was written', $after === $before + 1);

// the propagated message is served by OUR fetch and still re-verifies end-to-end
$got2 = Relay::fetch(['topic' => $topic, 'since' => 0]);
$prop = null;
foreach ($got2['messages'] as $mm) { if ($mm['id'] === $peerMsg['id']) $prop = $mm; }
check('peer message appears in local fetch', $prop !== null && $prop['body'] === $peerPayload);
check('  …and re-verifies end-to-end after the hop', $prop !== null
    && Crypto::verify($prop['from'],
        Relay::signedPreimage((string) ($prop['to'] ?? ''), $prop['topic'], $prop['body']),
        $prop['sig']));

// incremental + idempotent: the second pass asks since=<stored cursor> and ingests nothing
$rec2 = Relay::reconcile(['https://peer.example/molgang/api/relay'], $fakeHttp);
$p1 = $rec2['peers'][0] ?? [];
check('second pass is incremental (since=stored cursor → nothing new)',
    str_contains(end($peerCalls), 'since=102') && ($p1['new'] ?? -1) === 0);
check('replaying a known id through ingest() is a no-op',
    ($r = Relay::ingest($peerMsg)) && !empty($r['ok']) && !empty($r['known'])
    && (int) Db::one('SELECT COUNT(*) c FROM relay_message')['c'] === $after);

@unlink($dbfile);
echo $fail === 0 ? "\nRELAY SMOKE: PASS ✅\n" : "\nRELAY SMOKE: $fail FAILED ❌\n";
exit($fail === 0 ? 0 : 1);
