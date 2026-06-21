<?php
// Monitor — a READ-ONLY health lens over the live 5mart.ml knitweb node (Refs #59 #60 #61).
//
// Server-side companion to knitweb/monitor and the in-game 📡 Monitor tab. It returns, in ONE
// request-driven snapshot, everything the always-on PHP relay node can see about itself:
//   • the onboarded p2p node roster (who proved a wallet, who is online),
//   • relay store-and-forward throughput (totals, topics, recent envelopes — never bodies),
//   • the shared woven Knitweb (nodes/edges/state_root/anchor) — the knowledge-graph lens,
//   • game liveness (players / active sessions / woven fibers).
//
// It is STRICTLY READ-ONLY: only SELECT/COUNT, never an INSERT/UPDATE/DELETE, so polling it can
// never mutate node, relay or game state (see tests/monitor_smoke.php for the read-only proof).
// It reuses the canonical read methods the API already exposes (Relay::info/online, Bar::web),
// so the monitor can never drift from what those endpoints report.
declare(strict_types=1);

require_once __DIR__ . '/Db.php';
require_once __DIR__ . '/Relay.php';
require_once __DIR__ . '/Bar.php';

final class Monitor
{
    public const RECENT       = 12;    // cap rows in every "recent" list (bounded payload)
    public const SESSION_LIVE = 120;   // a game session is "active" if seen within this window (s)

    private static function now(): float { return microtime(true); }

    /** COUNT(*) helper that yields 0 if a table is absent — keeps the monitor robust on a partial DB. */
    private static function scalar(string $sql, array $args = []): int
    {
        try {
            return (int) (Db::one($sql, $args)['c'] ?? 0);
        } catch (Throwable $e) {
            return 0;
        }
    }

    /** The whole snapshot the dashboard polls. Read-only; safe to call on every tick. */
    public static function summary(): array
    {
        return [
            'node'     => self::node(),
            'registry' => self::registry(),
            'relay'    => self::relay(),
            'web'      => self::web(),
            'game'     => self::game(),
            'health'   => [
                'api_version'   => '1',
                'engine'        => 'php',
                'online_window' => Relay::ONLINE_WINDOW_S,
                'time'          => self::now(),
            ],
        ];
    }

    /** Identity/health card of the relay node itself (reuses the canonical /api/relay/info). */
    private static function node(): array
    {
        return Relay::info();
    }

    /** Onboarded p2p node roster: counts + recent verified onboards (public fields only). */
    private static function registry(): array
    {
        $registered = self::scalar('SELECT COUNT(*) c FROM node_registry WHERE revoked=0');
        $revoked    = self::scalar('SELECT COUNT(*) c FROM node_registry WHERE revoked=1');
        $online     = Relay::online();   // read-only; address/endpoint/age — never a secret

        $recent = [];
        try {
            $rows = Db::all(
                'SELECT address, endpoint, device_fp, registered, last_seen, revoked
                   FROM node_registry ORDER BY registered DESC LIMIT ' . self::RECENT
            );
            $now = self::now();
            foreach ($rows as $r) {
                $recent[] = [
                    'address'   => $r['address'],
                    'endpoint'  => $r['endpoint'],
                    'device_fp' => substr((string) $r['device_fp'], 0, 24),  // shown truncated
                    'age_s'     => round($now - (float) $r['last_seen'], 1),
                    'revoked'   => (int) $r['revoked'] === 1,
                ];
            }
        } catch (Throwable $e) { /* partial DB — leave recent empty */ }

        return [
            'registered'  => $registered,
            'revoked'     => $revoked,
            'online'      => count($online),
            'online_list' => $online,
            'recent'      => $recent,
        ];
    }

    /** Relay store-and-forward throughput: totals, topic breakdown, recent envelopes (no bodies). */
    private static function relay(): array
    {
        $total     = self::scalar('SELECT COUNT(*) c FROM relay_message');
        $broadcast = self::scalar('SELECT COUNT(*) c FROM relay_message WHERE to_addr IS NULL');

        $topics = [];
        try {
            foreach (Db::all(
                'SELECT topic, COUNT(*) c FROM relay_message GROUP BY topic ORDER BY c DESC LIMIT ' . self::RECENT
            ) as $r) {
                $topics[] = ['topic' => $r['topic'], 'count' => (int) $r['c']];
            }
        } catch (Throwable $e) { /* partial DB */ }

        $recent = [];
        try {
            // Envelope metadata only — NEVER the signed body (may be large; not ours to surface).
            foreach (Db::all(
                'SELECT id, from_pub, to_addr, topic, created FROM relay_message ORDER BY created DESC LIMIT ' . self::RECENT
            ) as $r) {
                $recent[] = [
                    'id'    => $r['id'],
                    'from'  => substr((string) $r['from_pub'], 0, 16) . '…',
                    'to'    => $r['to_addr'] ?: '*',
                    'topic' => $r['topic'],
                    'age_s' => round(self::now() - (float) $r['created'], 1),
                ];
            }
        } catch (Throwable $e) { /* partial DB */ }

        return [
            'messages'  => $total,
            'broadcast' => $broadcast,
            'addressed' => max(0, $total - $broadcast),
            'topics'    => $topics,
            'recent'    => $recent,
        ];
    }

    /** The shared woven Knitweb — the knowledge-graph lens (reuses the canonical Bar::web()). */
    private static function web(): array
    {
        try {
            $w = Bar::web();
        } catch (Throwable $e) {
            return ['nodes' => 0, 'edges' => 0, 'state_root' => null, 'anchored' => false,
                    'ual' => null, 'terms' => 0, 'links' => 0, 'recent' => []];
        }
        $anchor = $w['anchor'] ?? null;
        return [
            'nodes'      => (int) ($w['nodes'] ?? 0),
            'edges'      => (int) ($w['edges'] ?? 0),
            'state_root' => $w['state_root'] ?? null,
            'anchored'   => is_array($anchor) ? (bool) ($anchor['verified'] ?? false) : false,
            'ual'        => is_array($anchor) ? ($anchor['ual'] ?? null) : null,
            'terms'      => is_array($w['terms'] ?? null) ? count($w['terms']) : 0,
            'links'      => is_array($w['links'] ?? null) ? count($w['links']) : 0,
            'recent'     => array_slice($w['recent'] ?? [], 0, self::RECENT),
        ];
    }

    /** Game liveness — players, active sessions, woven fibers (read-only counts). */
    private static function game(): array
    {
        $cutoff = self::now() - self::SESSION_LIVE;
        return [
            'players'   => self::scalar('SELECT COUNT(*) c FROM player'),
            'bots'      => self::scalar('SELECT COUNT(*) c FROM player WHERE is_bot=1'),
            'sessions'  => self::scalar('SELECT COUNT(*) c FROM session'),
            'active'    => self::scalar('SELECT COUNT(*) c FROM session WHERE last_seen >= ?', [$cutoff]),
            'proposals' => self::scalar('SELECT COUNT(*) c FROM proposal'),
            'woven'     => self::scalar('SELECT COUNT(*) c FROM proposal WHERE woven=1'),
            'votes'     => self::scalar('SELECT COUNT(*) c FROM vote'),
        ];
    }
}
