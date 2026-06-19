<?php
// Full-engine smoke test — join → sit → knit → bot quorum → woven → web → presence.
// Runs against an in-process SQLite DB (no server, no MySQL needed): php php/tests/smoke.php
declare(strict_types=1);

require __DIR__ . '/../src/Db.php';
require __DIR__ . '/../src/Bar.php';

$dbfile = tempnam(sys_get_temp_dir(), 'mg_smoke_') . '.sqlite';
$pdo = new PDO('sqlite:' . $dbfile);
$pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
$pdo->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);
Db::setPdo($pdo);

// SQLite-compatible tables (same columns as schema.sql; the app SQL is portable).
$pdo->exec('CREATE TABLE player(device_id TEXT PRIMARY KEY,name TEXT,avatar TEXT,address TEXT,pulses INT,silk INT,xp INT,is_bot INT,created REAL)');
$pdo->exec('CREATE TABLE session(sid TEXT PRIMARY KEY,device_id TEXT,table_id TEXT,last_seen REAL)');
$pdo->exec('CREATE TABLE proposal(pid TEXT PRIMARY KEY,table_id TEXT,proposer TEXT,by_name TEXT,term TEXT,kind TEXT,subject TEXT,relation TEXT,obj TEXT,topic TEXT,settled INT DEFAULT 0,outcome TEXT,woven INT DEFAULT 0,fiber_cid TEXT,is_chem INT DEFAULT 0,created REAL)');
$pdo->exec('CREATE TABLE vote(pid TEXT,voter TEXT,verdict TEXT,created REAL,PRIMARY KEY(pid,voter))');
$pdo->exec('CREATE TABLE presence(device_id TEXT,client TEXT,last_seen REAL,first_seen REAL,info TEXT,PRIMARY KEY(device_id,client))');

$fail = 0;
function check(string $label, bool $ok): void
{
    global $fail;
    echo ($ok ? '  ok  ' : '  FAIL') . " — $label\n";
    if (!$ok) {
        $fail++;
    }
}

$j = Bar::join('Edwin', 'laser-maxi', 'dev-edwin');
check('join returns sid + deterministic pls1 wallet', isset($j['sid']) && str_starts_with($j['address'], 'pls1'));

Bar::sit($j['sid'], 'periodic');
$p = Bar::propose($j['sid'], 'CH4 is methane');
check('propose returns a pid', isset($p['pid']));

$st = Bar::state($j['sid']);
$periodic = null;
foreach ($st['tables'] as $t) {
    if ($t['id'] === 'periodic') {
        $periodic = $t;
    }
}
check('bots seated (3 at the table)', count($periodic['seated']) === 3);
check('claim woven by quorum into the fabric', count($periodic['fabric']) === 1);
check('knit cost 1 silk (10 → 9)', $st['you']['silk'] === 9);
check('weaving granted XP (level 2)', $st['you']['level'] === 2);
check('bar_woven counts it', $st['bar_woven'] === 1);

$w = Bar::web();
check('web has the CH4 → methane link', $w['edges'] === 1 && $w['links'][0]['subject'] === 'CH4');
check('web is OriginTrail-anchored + verified', $w['anchor'] && $w['anchor']['verified'] === true);

Bar::beat('dev-edwin', 'desktop', 'molgang-desktop test');
$peers = Bar::presenceFor('dev-edwin');
check('cross-client presence: web + desktop both active', $peers['web']['active'] && $peers['desktop']['active']);

$own = Bar::vote($j['sid'], $p['pid'], 'confirm');
check('cannot double-resolve a settled knit', isset($own['error']));

// --- #53: an abandoned (stale) seat must be reaped so it can't inflate the quorum ---
$now = microtime(true);
$pdo->exec("INSERT INTO player(device_id,name,avatar,address,pulses,silk,xp,is_bot,created)
            VALUES('ghost','Ghosty','gas-goblin','pls1ghost',50,10,0,0,$now)");           // a real player who vanished…
$pdo->exec("INSERT INTO session(sid,device_id,table_id,last_seen) VALUES('gsid','ghost','organic'," . ($now - 9999) . ")"); // …hours ago, still 'seated'
$g = Bar::join('Mara', 'hoodie-hacker', 'dev-mara');     // a fresh human sits at the same table and knits solo
Bar::sit($g['sid'], 'organic');
Bar::propose($g['sid'], 'CO2 is carbon dioxide');         // committee would be 3 (→quorum 3) WITH the ghost; only 2 bots vote
$st2 = Bar::state($g['sid']);
$organic = null;
foreach ($st2['tables'] as $t) { if ($t['id'] === 'organic') { $organic = $t; } }
check('#53: stale ghost seat reaped (not rendered)', !in_array('Ghosty', array_column($organic['seated'], 'name'), true));
check('#53: solo knit weaves once the ghost no longer inflates the quorum', count($organic['fabric']) === 1);

@unlink($dbfile);
echo $fail === 0 ? "\nSMOKE: PASS ✅\n" : "\nSMOKE: $fail FAILED ❌\n";
exit($fail === 0 ? 0 : 1);
