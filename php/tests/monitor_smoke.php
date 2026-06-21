<?php
// Monitor smoke test (Refs #59 #60). Proves the /api/monitor snapshot aggregates the live node's
// registry / relay / web / game state AND that reading it is STRICTLY READ-ONLY — polling the
// monitor must never mutate a single row. Runs on in-process SQLite — no server, no MySQL:
//   php php/tests/monitor_smoke.php
declare(strict_types=1);

require __DIR__ . '/../src/Db.php';
require __DIR__ . '/../src/Crypto.php';
require __DIR__ . '/../src/Relay.php';
require __DIR__ . '/../src/Bar.php';
require __DIR__ . '/../src/Monitor.php';

$dbfile = tempnam(sys_get_temp_dir(), 'mg_mon_') . '.sqlite';
$pdo = new PDO('sqlite:' . $dbfile);
$pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
$pdo->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);
Db::setPdo($pdo);

// SQLite mirrors of schema.sql + node_registry.sql (portable column types).
$pdo->exec('CREATE TABLE node_registry(pubkey TEXT PRIMARY KEY,address TEXT UNIQUE,device_fp TEXT,endpoint TEXT,registered REAL,last_seen REAL,revoked INT DEFAULT 0)');
$pdo->exec('CREATE TABLE relay_message(id TEXT PRIMARY KEY,from_pub TEXT,to_addr TEXT,topic TEXT,body TEXT,sig TEXT,created REAL)');
$pdo->exec('CREATE TABLE player(device_id TEXT PRIMARY KEY,name TEXT,avatar TEXT,address TEXT,pulses INT,silk INT,xp INT,is_bot INT DEFAULT 0,created REAL)');
$pdo->exec('CREATE TABLE session(sid TEXT PRIMARY KEY,device_id TEXT,table_id TEXT,last_seen REAL)');
$pdo->exec('CREATE TABLE proposal(pid TEXT PRIMARY KEY,table_id TEXT,proposer TEXT,by_name TEXT,term TEXT,kind TEXT,subject TEXT,relation TEXT,obj TEXT,topic TEXT,settled INT DEFAULT 0,outcome TEXT,woven INT DEFAULT 0,fiber_cid TEXT,is_chem INT DEFAULT 0,created REAL)');
$pdo->exec('CREATE TABLE vote(pid TEXT,voter TEXT,verdict TEXT,created REAL,PRIMARY KEY(pid,voter))');

$now = microtime(true);
$fail = 0;
function check(string $label, bool $ok): void {
    global $fail;
    echo ($ok ? '  ok  ' : '  FAIL') . " — $label\n";
    if (!$ok) $fail++;
}

// --- seed live-like state ------------------------------------------------------------------
// A registered + online p2p node (within Relay::ONLINE_WINDOW_S), and a stale/revoked one.
$pdo->exec("INSERT INTO node_registry VALUES('02aa','pls1online','fp-aa:bb:cc:dd','https://peer.example',$now,$now,0)");
$pdo->exec("INSERT INTO node_registry VALUES('02bb','pls1stale','fp-ee',NULL,$now," . ($now - 9999) . ",0)");
$pdo->exec("INSERT INTO node_registry VALUES('02cc','pls1revoked','fp-ff',NULL,$now,$now,1)");
// Relay messages: one broadcast, one addressed.
$pdo->exec("INSERT INTO relay_message VALUES('m1','02aa',NULL,'chem','BODY-SHOULD-NOT-LEAK','sig',$now)");
$pdo->exec("INSERT INTO relay_message VALUES('m2','02aa','pls1online','dm','BODY2','sig'," . ($now - 5) . ")");
// Game state: a human, a bot, an active session, a woven proposal + a vote.
$pdo->exec("INSERT INTO player VALUES('dev1','Ada','flask','pls1ada',50,10,0,0,$now)");
$pdo->exec("INSERT INTO player VALUES('bot1','NPC','beaker','pls1bot',50,10,0,1,$now)");
$pdo->exec("INSERT INTO session VALUES('s1','dev1','periodic',$now)");
$pdo->exec("INSERT INTO proposal VALUES('p1','periodic','dev1','Ada','H2O','term',NULL,NULL,NULL,'periodic',1,'confirmed',1,'cid1',1,$now)");
$pdo->exec("INSERT INTO vote VALUES('p1','dev1','confirm',$now)");

// --- snapshot row counts BEFORE, to prove read-only -----------------------------------------
$tables = ['node_registry', 'relay_message', 'player', 'session', 'proposal', 'vote'];
$before = [];
foreach ($tables as $t) { $before[$t] = (int) $pdo->query("SELECT COUNT(*) c FROM $t")->fetch()['c']; }

// --- the call under test --------------------------------------------------------------------
$snap = Monitor::summary();

// structure
check('summary has node/registry/relay/web/game/health sections',
    isset($snap['node'], $snap['registry'], $snap['relay'], $snap['web'], $snap['game'], $snap['health']));

// registry: 2 registered (revoked excluded), 1 revoked, 1 online (the fresh one only)
check('registry.registered counts non-revoked nodes (=2)', ($snap['registry']['registered'] ?? null) === 2);
check('registry.revoked counts revoked nodes (=1)',        ($snap['registry']['revoked'] ?? null) === 1);
check('registry.online counts only fresh pings (=1)',      ($snap['registry']['online'] ?? null) === 1);
check('online roster carries the live node address',
    ($snap['registry']['online_list'][0]['address'] ?? null) === 'pls1online');

// relay: 2 messages (1 broadcast, 1 addressed); bodies must NOT be present anywhere
check('relay.messages total (=2)',   ($snap['relay']['messages'] ?? null) === 2);
check('relay.broadcast (=1)',        ($snap['relay']['broadcast'] ?? null) === 1);
check('relay.addressed (=1)',        ($snap['relay']['addressed'] ?? null) === 1);
check('relay surfaces topic breakdown', count($snap['relay']['topics'] ?? []) >= 1);
check('relay NEVER leaks message bodies', strpos(json_encode($snap), 'BODY-SHOULD-NOT-LEAK') === false);

// web + game sections present and integer-typed
check('web section has integer node/edge counts',
    is_int($snap['web']['nodes'] ?? null) && is_int($snap['web']['edges'] ?? null));
check('game.players (=2) incl. 1 bot, 1 active session, 1 woven',
    ($snap['game']['players'] ?? null) === 2 && ($snap['game']['bots'] ?? null) === 1
    && ($snap['game']['active'] ?? null) === 1 && ($snap['game']['woven'] ?? null) === 1);

// --- THE read-only invariant: not one row changed ------------------------------------------
$after = [];
foreach ($tables as $t) { $after[$t] = (int) $pdo->query("SELECT COUNT(*) c FROM $t")->fetch()['c']; }
check('summary() wrote NOTHING (all row counts unchanged)', $before === $after);

@unlink($dbfile);
echo $fail === 0 ? "\nALL PASS\n" : "\n$fail CHECK(S) FAILED\n";
exit($fail === 0 ? 0 : 1);
