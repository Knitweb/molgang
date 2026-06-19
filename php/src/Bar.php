<?php
// Bar — the MOLGANG game engine (MySQL-backed, request-driven; no long-lived process).
// Faithful PHP port of src/molgang/{bar,game}.py: join → sit → knit → peer quorum → weave.
declare(strict_types=1);

require_once __DIR__ . '/Db.php';
require_once __DIR__ . '/Parse.php';
require_once __DIR__ . '/Chemistry.php';
require_once __DIR__ . '/Progression.php';

final class Bar
{
    public const FAUCET_PULSES = 50;
    public const FAUCET_SILK = 10;
    public const VOTE_COST = 1;
    public const SILK_PER_BOND = 1;
    public const SEATS_PER_TABLE = 6;
    public const BOTS_PER_TABLE = 2;
    public const PRESENCE_ACTIVE_S = 30;   // a client is "active" if it beat within this window
    public const SEAT_TTL_S = 120;         // a non-bot seat is reaped if its session goes silent this long

    public const AVATARS = [
        ['id' => 'laser-maxi', 'name' => 'Laser-Eyes Maxi'],
        ['id' => 'hoodie-hacker', 'name' => 'Hoodie Hacker'],
        ['id' => 'gas-goblin', 'name' => 'Gas-Fee Goblin'],
        ['id' => 'dao-delegate', 'name' => 'DAO Delegate'],
        ['id' => 'diamond-hands', 'name' => 'Diamond Hands'],
        ['id' => 'validator-owl', 'name' => 'Validator Owl'],
        ['id' => 'faucet-fairy', 'name' => 'Faucet Fairy'],
        ['id' => 'degen-ape', 'name' => 'Degen Ape'],
    ];
    public const TABLES = [
        ['id' => 'periodic', 'name' => 'Periodic Bar'],
        ['id' => 'organic', 'name' => 'Organic Lounge'],
        ['id' => 'noble', 'name' => 'Noble Corner'],
    ];
    private const BOT_NAMES = ['🤖 Bea', '🤖 Cy', '🤖 Dex', '🤖 Vala', '🤖 Mo', '🤖 Pim'];

    private static function now(): float { return microtime(true); }
    private static function avatarIds(): array { return array_column(self::AVATARS, 'id'); }

    /** Deterministic pls1… wallet from a device id (same id → same wallet, no stored key). */
    public static function address(string $device): string
    {
        return 'pls1' . substr(hash('sha256', 'molgang:account:seed:' . $device), 0, 38);
    }

    private static function fiberCid(string $payload): string
    {
        return 'bafyrei' . substr(self::b32(hash('sha256', $payload, true)), 0, 52);
    }

    private static function b32(string $bytes): string
    {
        $alpha = 'abcdefghijklmnopqrstuvwxyz234567';
        $bits = '';
        foreach (str_split($bytes) as $c) {
            $bits .= str_pad(decbin(ord($c)), 8, '0', STR_PAD_LEFT);
        }
        $out = '';
        foreach (str_split($bits, 5) as $chunk) {
            $out .= $alpha[bindec(str_pad($chunk, 5, '0'))];
        }
        return $out;
    }

    // ---- identity / seeding -------------------------------------------------

    private static function ensurePlayer(string $device, ?string $name, ?string $avatar, bool $bot = false): array
    {
        $p = Db::one('SELECT * FROM player WHERE device_id=?', [$device]);
        if ($p === null) {
            $av = in_array($avatar, self::avatarIds(), true) ? $avatar
                : self::avatarIds()[abs(crc32($device)) % count(self::avatarIds())];
            Db::run(
                'INSERT INTO player (device_id,name,avatar,address,pulses,silk,xp,is_bot,created)
                 VALUES (?,?,?,?,?,?,0,?,?)',
                [$device, $name ?: 'guest', $av, self::address($device),
                 self::FAUCET_PULSES, self::FAUCET_SILK, $bot ? 1 : 0, self::now()]
            );
            $p = Db::one('SELECT * FROM player WHERE device_id=?', [$device]);
        } elseif (!$bot && ($name || $avatar)) {
            $av = in_array($avatar, self::avatarIds(), true) ? $avatar : $p['avatar'];
            Db::run('UPDATE player SET name=?, avatar=? WHERE device_id=?',
                [$name ?: $p['name'], $av, $device]);
            $p['name'] = $name ?: $p['name'];
            $p['avatar'] = $av;
        }
        return $p;
    }

    /** Seed 2 NPC table-mates per table once, so a solo human can still reach a quorum. */
    private static function ensureBots(): void
    {
        $i = 0;
        foreach (self::TABLES as $t) {
            for ($k = 0; $k < self::BOTS_PER_TABLE; $k++) {
                $device = "bot:{$t['id']}:$k";
                if (Db::one('SELECT device_id FROM player WHERE device_id=?', [$device]) === null) {
                    $name = self::BOT_NAMES[$i % count(self::BOT_NAMES)];
                    $av = self::avatarIds()[$i % count(self::avatarIds())];
                    Db::run('INSERT INTO player (device_id,name,avatar,address,pulses,silk,xp,is_bot,created)
                             VALUES (?,?,?,?,?,?,0,1,?)',
                        [$device, $name, $av, self::address($device), 9999, 0, self::now()]);
                    Db::run('INSERT INTO session (sid,device_id,table_id,last_seen) VALUES (?,?,?,?)',
                        ['bs:' . bin2hex(random_bytes(8)), $device, $t['id'], self::now()]);
                }
                $i++;
            }
        }
    }

    // ---- presence (cross-client awareness) ----------------------------------

    public static function beat(string $device, string $client, ?string $info = null): void
    {
        $client = $client === 'desktop' ? 'desktop' : 'web';
        $now = self::now();
        // Portable upsert (works on MySQL and SQLite): update if present, else insert.
        $exists = Db::one('SELECT 1 x FROM presence WHERE device_id=? AND client=?', [$device, $client]);
        if ($exists !== null) {
            Db::run('UPDATE presence SET last_seen=?, info=COALESCE(?,info) WHERE device_id=? AND client=?',
                [$now, $info, $device, $client]);
        } else {
            Db::run('INSERT INTO presence (device_id,client,last_seen,first_seen,info) VALUES (?,?,?,?,?)',
                [$device, $client, $now, $now, $info]);
        }
    }

    /** What each client knows about the other for this device→wallet identity. */
    public static function presenceFor(string $device): array
    {
        $now = self::now();
        $out = [];
        foreach (['web', 'desktop'] as $c) {
            $r = Db::one('SELECT last_seen,first_seen,info FROM presence WHERE device_id=? AND client=?', [$device, $c]);
            $out[$c] = $r === null
                ? ['active' => false, 'used_before' => false, 'last_seen' => null, 'info' => null]
                : [
                    'active' => ($now - (float) $r['last_seen']) <= self::PRESENCE_ACTIVE_S,
                    'used_before' => true,
                    'last_seen' => (float) $r['last_seen'],
                    'info' => $r['info'],
                ];
        }
        return $out;
    }

    // ---- session lifecycle --------------------------------------------------

    public static function join(string $name, ?string $avatar, string $device): array
    {
        self::ensureBots();
        $p = self::ensurePlayer($device, $name, $avatar);
        Db::run('DELETE FROM session WHERE device_id=?', [$device]);   // one live session per device
        $sid = bin2hex(random_bytes(8));
        Db::run('INSERT INTO session (sid,device_id,table_id,last_seen) VALUES (?,?,NULL,?)', [$sid, $device, self::now()]);
        self::beat($device, 'web');
        return ['sid' => $sid, 'avatar' => $p['avatar'], 'address' => $p['address']];
    }

    private static function session(string $sid): ?array
    {
        $s = Db::one('SELECT * FROM session WHERE sid=?', [$sid]);
        if ($s !== null) {
            Db::run('UPDATE session SET last_seen=? WHERE sid=?', [self::now(), $sid]);
        }
        return $s;
    }

    public static function sit(string $sid, string $tableId): array
    {
        $s = self::session($sid);
        if ($s === null) return ['error' => 'unknown session'];
        if (!in_array($tableId, array_column(self::TABLES, 'id'), true)) return ['error' => 'no such table'];
        self::reapStale();                          // a stale-full table should still admit a real player
        if (self::seatedCount($tableId) >= self::SEATS_PER_TABLE && $s['table_id'] !== $tableId) {
            return ['error' => 'table full'];
        }
        Db::run('UPDATE session SET table_id=? WHERE sid=?', [$tableId, $sid]);
        return ['ok' => true];
    }

    private static function seatedCount(string $tableId): int
    {
        return (int) (Db::one('SELECT COUNT(*) c FROM session WHERE table_id=?', [$tableId])['c'] ?? 0);
    }

    /**
     * Free seats whose session has gone silent past SEAT_TTL_S. Active clients
     * bump session.last_seen on every poll (see session()), so only abandoned
     * tabs/test sessions go stale. Bots never poll, so they are never reaped —
     * otherwise the 2 NPC table-mates would vanish and a solo human could never
     * reach quorum. Without this, stale seats inflate the seat-scaled quorum in
     * settle() and a solo knit never weaves (issue #53).
     */
    private static function reapStale(): void
    {
        Db::run(
            'DELETE FROM session WHERE last_seen < ? AND device_id NOT IN (SELECT device_id FROM player WHERE is_bot=1)',
            [self::now() - self::SEAT_TTL_S]
        );
    }

    // ---- knit / vote / settle ----------------------------------------------

    public static function propose(string $sid, string $term): array
    {
        $s = self::session($sid);
        if ($s === null) return ['error' => 'unknown session'];
        if (!$s['table_id']) return ['error' => 'sit at a table first'];
        $p = Db::one('SELECT * FROM player WHERE device_id=?', [$s['device_id']]);
        if ((int) $p['silk'] < self::SILK_PER_BOND) return ['error' => 'not enough silk to knit'];

        $parsed = Parse::knit($term);
        $label = $parsed['label'];
        if ($label === '') return ['error' => 'type a term to knit'];
        $topic = $parsed['kind'] === 'link' ? $parsed['subject'] : ($parsed['term'] ?? $label);

        Db::run('UPDATE player SET silk=silk-? WHERE device_id=?', [self::SILK_PER_BOND, $s['device_id']]);
        $pid = bin2hex(random_bytes(8));
        Db::run(
            'INSERT INTO proposal (pid,table_id,proposer,by_name,term,kind,subject,relation,obj,topic,is_chem,created)
             VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
            [$pid, $s['table_id'], $s['device_id'], $p['name'], $label, $parsed['kind'],
             $parsed['subject'] ?? null, $parsed['relation'] ?? null, $parsed['object'] ?? null,
             $topic, Chemistry::isChemistry($topic) ? 1 : 0, self::now()]
        );
        self::botsAct($s['table_id']);   // NPC table-mates weigh in immediately
        return ['pid' => $pid];
    }

    public static function vote(string $sid, string $pid, string $verdict): array
    {
        $s = self::session($sid);
        if ($s === null) return ['error' => 'unknown session'];
        return self::castVote($s['device_id'], $pid, $verdict);
    }

    private static function castVote(string $voter, string $pid, string $verdict): array
    {
        $verdict = in_array($verdict, ['confirm', 'mismatch', 'abstain'], true) ? $verdict : 'abstain';
        $prop = Db::one('SELECT * FROM proposal WHERE pid=?', [$pid]);
        if ($prop === null) return ['error' => 'no such knit'];
        if ((int) $prop['settled'] === 1) return ['error' => 'already settled'];
        if ($prop['proposer'] === $voter) return ['error' => 'cannot vote on your own knit'];
        if (Db::one('SELECT 1 x FROM vote WHERE pid=? AND voter=?', [$pid, $voter]) !== null) {
            return ['error' => 'already voted'];
        }
        $p = Db::one('SELECT pulses FROM player WHERE device_id=?', [$voter]);
        if ($p === null || (int) $p['pulses'] < self::VOTE_COST) return ['error' => 'not enough pulses to vote'];
        Db::run('UPDATE player SET pulses=pulses-? WHERE device_id=?', [self::VOTE_COST, $voter]);  // the vote stakes a pulse
        Db::run('INSERT INTO vote (pid,voter,verdict,created) VALUES (?,?,?,?)', [$pid, $voter, $verdict, self::now()]);
        self::settle($pid);
        return ['ok' => true];
    }

    /** Seated NPCs vote on open knits they haven't weighed in on (honest verdict). */
    private static function botsAct(string $tableId): void
    {
        $bots = Db::all('SELECT s.device_id FROM session s JOIN player pl ON pl.device_id=s.device_id
                         WHERE s.table_id=? AND pl.is_bot=1', [$tableId]);
        $open = Db::all('SELECT * FROM proposal WHERE table_id=? AND settled=0', [$tableId]);
        foreach ($open as $prop) {
            $parsed = [
                'kind' => $prop['kind'], 'term' => $prop['term'], 'label' => $prop['term'],
                'subject' => $prop['subject'], 'object' => $prop['obj'],
            ];
            $verdict = Chemistry::soundClaim($parsed) ? 'confirm' : 'mismatch';
            foreach ($bots as $b) {
                if ($b['device_id'] === $prop['proposer']) continue;
                if (Db::one('SELECT 1 x FROM vote WHERE pid=? AND voter=?', [$prop['pid'], $b['device_id']]) !== null) continue;
                Db::run('INSERT INTO vote (pid,voter,verdict,created) VALUES (?,?,?,?)',
                    [$prop['pid'], $b['device_id'], $verdict, self::now()]);
            }
            self::settle($prop['pid']);
        }
    }

    /** BFT confirm-quorum over the table committee → weave a Fiber (or settle as mismatch). */
    private static function settle(string $pid): void
    {
        $prop = Db::one('SELECT * FROM proposal WHERE pid=?', [$pid]);
        if ($prop === null || (int) $prop['settled'] === 1) return;
        self::reapStale();                          // committee must reflect *active* seats, not ghosts (#53)
        $v = self::voteBreakdown($pid);
        $committee = max(1, self::seatedCount($prop['table_id']) - 1);   // seated minus the proposer
        $quorum = max(2, intdiv(2 * $committee, 3) + 1);                 // BFT supermajority, floor 2
        if ($v['confirm'] >= $quorum && $v['confirm'] > $v['mismatch']) {
            $cid = self::fiberCid($prop['term'] . '|' . $prop['proposer'] . '|' . $prop['created']);
            Db::run('UPDATE proposal SET settled=1, woven=1, outcome=?, fiber_cid=? WHERE pid=?', ['confirmed', $cid, $pid]);
            Db::run('UPDATE player SET xp=xp+? WHERE device_id=?', [Progression::XP_PER_WOVEN, $prop['proposer']]);
        } elseif ($v['mismatch'] >= $quorum && $v['mismatch'] >= $v['confirm']) {
            Db::run('UPDATE proposal SET settled=1, outcome=? WHERE pid=?', ['mismatch', $pid]);
        }
    }

    private static function voteBreakdown(string $pid): array
    {
        $rows = Db::all('SELECT verdict, COUNT(*) c FROM vote WHERE pid=? GROUP BY verdict', [$pid]);
        $b = ['confirm' => 0, 'mismatch' => 0, 'abstain' => 0];
        foreach ($rows as $r) { $b[$r['verdict']] = (int) $r['c']; }
        $b['total'] = $b['confirm'] + $b['mismatch'] + $b['abstain'];
        $b['net'] = $b['confirm'] - $b['mismatch'];
        return $b;
    }

    // ---- read models (state / web / graph) ----------------------------------

    public static function state(?string $sid): array
    {
        self::ensureBots();
        self::reapStale();                          // drop abandoned seats before rendering the floor
        $me = $sid ? self::session($sid) : null;
        $meDev = $me['device_id'] ?? null;
        if ($meDev) self::beat($meDev, 'web');

        $tables = [];
        foreach (self::TABLES as $t) {
            $seated = [];
            $rows = Db::all('SELECT s.device_id, pl.name, pl.avatar, pl.xp FROM session s
                             JOIN player pl ON pl.device_id=s.device_id WHERE s.table_id=? ORDER BY pl.is_bot, s.last_seen', [$t['id']]);
            foreach ($rows as $r) {
                $lvl = Progression::levelFor((int) $r['xp']);
                $seated[] = [
                    'name' => $r['name'], 'avatar' => $r['avatar'], 'you' => $r['device_id'] === $meDev,
                    'level' => $lvl, 'title' => Progression::titleFor($lvl), 'woven' => self::wovenBy($r['device_id']),
                ];
            }
            $open = [];
            foreach (Db::all('SELECT * FROM proposal WHERE table_id=? AND settled=0 ORDER BY created', [$t['id']]) as $p) {
                $open[] = [
                    'pid' => $p['pid'], 'term' => $p['term'], 'by' => $p['by_name'],
                    'votes' => self::voteBreakdown($p['pid']),
                    'mine' => $p['proposer'] === $meDev,
                    'voted' => $meDev !== null && Db::one('SELECT 1 x FROM vote WHERE pid=? AND voter=?', [$p['pid'], $meDev]) !== null,
                ];
            }
            $fabric = [];
            foreach (Db::all('SELECT * FROM proposal WHERE table_id=? AND woven=1 ORDER BY created', [$t['id']]) as $p) {
                $fabric[] = ['term' => $p['term'], 'fiber_cid' => $p['fiber_cid'],
                    'confirmations' => self::voteBreakdown($p['pid'])['confirm'], 'is_chemistry' => (bool) $p['is_chem']];
            }
            $tables[] = ['id' => $t['id'], 'name' => $t['name'], 'seats' => self::SEATS_PER_TABLE,
                'seated' => $seated, 'open' => $open, 'fabric' => $fabric];
        }

        $you = null;
        if ($me) {
            $p = Db::one('SELECT * FROM player WHERE device_id=?', [$meDev]);
            $lvl = Progression::levelFor((int) $p['xp']);
            $you = [
                'name' => $p['name'], 'avatar' => $p['avatar'], 'address' => $p['address'],
                'pulses' => (int) $p['pulses'], 'silk' => (int) $p['silk'],
                'knits_made' => (int) (Db::one('SELECT COUNT(*) c FROM proposal WHERE proposer=?', [$meDev])['c'] ?? 0),
                'woven' => self::wovenBy($meDev), 'level' => $lvl, 'title' => Progression::titleFor($lvl),
                'table' => $me['table_id'],
            ];
        }

        return [
            'tables' => $tables,
            'avatars' => self::AVATARS,
            'you' => $you,
            'my_knits' => $meDev ? self::myKnits($meDev) : null,
            'explorer' => self::explorer(),
            'bar_woven' => (int) (Db::one('SELECT COUNT(*) c FROM proposal WHERE woven=1')['c'] ?? 0),
            'pulse_host' => self::pulseHost(),
            'peers' => $meDev ? self::presenceFor($meDev) : null,   // cross-client awareness (web/desktop)
        ];
    }

    private static function wovenBy(string $device): int
    {
        return (int) (Db::one('SELECT COUNT(*) c FROM proposal WHERE proposer=? AND woven=1', [$device])['c'] ?? 0);
    }

    private static function pulseHost(): array
    {
        $addr = self::address('molgang:dapp:pulse-host');
        return ['account' => ['address' => $addr, 'balance_pls' => 1000], 'wallet' => 'dapp'];
    }

    private static function myKnits(string $device): array
    {
        $knits = [];
        $rows = Db::all('SELECT * FROM proposal WHERE proposer=? ORDER BY created DESC', [$device]);
        $totalVotes = 0; $woven = 0;
        foreach ($rows as $p) {
            $v = self::voteBreakdown($p['pid']);
            $totalVotes += $v['total'];
            if ((int) $p['woven'] === 1) $woven++;
            $knits[] = ['term' => $p['term'], 'topic' => $p['topic'], 'woven' => (bool) $p['woven'],
                'settled' => (bool) $p['settled'], 'outcome' => $p['outcome'], 'votes' => $v, 'fiber_cid' => $p['fiber_cid']];
        }
        return ['knits_made' => count($rows), 'woven' => $woven, 'total_votes' => $totalVotes, 'knits' => $knits];
    }

    private static function explorer(): array
    {
        $byTopic = [];
        foreach (Db::all('SELECT * FROM proposal ORDER BY created') as $p) {
            $byTopic[$p['topic']][] = $p;
        }
        $rows = [];
        foreach ($byTopic as $topic => $props) {
            $cols = [];
            foreach ($props as $p) {
                $v = self::voteBreakdown($p['pid']);
                $cols[] = ['pid' => $p['pid'], 'term' => $p['term'], 'by' => $p['by_name'], 'topic' => $topic,
                    'settled' => (bool) $p['settled'], 'outcome' => $p['outcome'], 'woven' => (bool) $p['woven'],
                    'fiber_cid' => $p['fiber_cid'], 'votes' => $v, 'net' => $v['net']];
            }
            usort($cols, fn($a, $b) => $b['net'] <=> $a['net']);
            $rows[] = ['topic' => $topic, 'competing' => count($cols), 'columns' => $cols];
        }
        usort($rows, fn($a, $b) => $b['competing'] <=> $a['competing']);
        return $rows;
    }

    // ---- the shared woven web + graph --------------------------------------

    public static function web(): array
    {
        $woven = Db::all('SELECT * FROM proposal WHERE woven=1 ORDER BY created');
        $nodes = []; $links = []; $recent = [];
        foreach ($woven as $p) {
            if ($p['kind'] === 'link') {
                $nodes[$p['subject']] = true; $nodes[$p['obj']] = true;
                $links[] = ['subject' => $p['subject'], 'relation' => $p['relation'], 'object' => $p['obj'], 'by' => $p['by_name']];
            } else {
                $nodes[$p['term']] = true;
            }
        }
        foreach (array_slice(array_reverse($woven), 0, 12) as $p) {
            $recent[] = ['kind' => $p['kind'], 'label' => $p['term'], 'by' => $p['by_name'],
                'confirmations' => self::voteBreakdown($p['pid'])['confirm'], 'fiber' => $p['fiber_cid']];
        }
        $terms = array_keys($nodes);
        sort($terms);
        $stateRoot = hash('sha256', implode("\n", $terms));
        $n = count($terms); $e = count($links);
        $anchor = $e > 0 ? [
            'ual' => 'did:dkg:knitweb/' . self::fiberCid('anchor:' . $stateRoot),
            'state_root' => $stateRoot,
            'receipt_cid' => self::fiberCid('receipt:' . $stateRoot),
            'verified' => true, 'nodes' => $n, 'edges' => $e,
        ] : null;
        return ['nodes' => $n, 'edges' => $e, 'state_root' => $stateRoot,
            'recent' => $recent, 'links' => $links, 'terms' => $terms, 'anchor' => $anchor];
    }

    public static function graph(array $q): array
    {
        $links = self::web()['links'];
        $adj = []; $radj = []; $deg = [];
        foreach ($links as $l) {
            $adj[$l['subject']][] = ['to' => $l['object'], 'relation' => $l['relation']];
            $radj[$l['object']][] = ['from' => $l['subject'], 'relation' => $l['relation']];
            $deg[$l['subject']] = ($deg[$l['subject']] ?? 0) + 1;
            $deg[$l['object']] = ($deg[$l['object']] ?? 0) + 1;
        }
        if (!empty($q['term'])) {
            $t = $q['term'];
            if (!isset($adj[$t]) && !isset($radj[$t])) return ['neighbors' => null];
            return ['neighbors' => ['out' => $adj[$t] ?? [], 'in' => $radj[$t] ?? []]];
        }
        if (!empty($q['from']) && !empty($q['to'])) {
            return ['path' => self::shortestPath($adj, $q['from'], $q['to'])];
        }
        arsort($deg);
        $hubs = [];
        foreach (array_slice($deg, 0, 8, true) as $term => $d) {
            $hubs[] = ['term' => $term, 'degree' => $d, 'centrality' => round($d / max(1, count($deg)), 3)];
        }
        $nodes = count($deg); $edges = count($links);
        return ['stats' => ['nodes' => $nodes, 'edges' => $edges, 'clusters' => self::components($adj, $radj),
            'density' => $nodes > 1 ? round($edges / ($nodes * ($nodes - 1)), 3) : 0], 'hubs' => $hubs];
    }

    private static function shortestPath(array $adj, string $a, string $b): ?array
    {
        if ($a === $b) return ['hops' => 0, 'path' => [$a]];
        $q = [[$a]]; $seen = [$a => true];
        while ($q) {
            $path = array_shift($q);
            $node = end($path);
            foreach ($adj[$node] ?? [] as $nb) {
                $to = $nb['to'];
                if (isset($seen[$to])) continue;
                $np = array_merge($path, [$to]);
                if ($to === $b) return ['hops' => count($np) - 1, 'path' => $np];
                $seen[$to] = true; $q[] = $np;
            }
        }
        return ['path' => null];
    }

    private static function components(array $adj, array $radj): int
    {
        $nodes = array_unique(array_merge(array_keys($adj), array_keys($radj)));
        $seen = []; $c = 0;
        foreach ($nodes as $n) {
            if (isset($seen[$n])) continue;
            $c++; $stack = [$n];
            while ($stack) {
                $x = array_pop($stack);
                if (isset($seen[$x])) continue;
                $seen[$x] = true;
                foreach (($adj[$x] ?? []) as $e) $stack[] = $e['to'];
                foreach (($radj[$x] ?? []) as $e) $stack[] = $e['from'];
            }
        }
        return $c;
    }
}
