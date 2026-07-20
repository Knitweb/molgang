<?php
// Relay — host-neutral HTTP relay + presence node for the knitweb (Refs #61).
//
// WHY HTTP and not raw p2p: this is shared hosting. A process here CAN bind a local socket, but a
// perimeter firewall drops all inbound TCP from the internet (verified — see php/PORTCHECK.md / #62),
// so a listening peer is unreachable. The always-on transport that IS reachable is nginx → PHP over
// HTTPS. So peers reach each other request-driven: a node POSTs a (signed) message here, the relay
// stores it in MySQL, and the recipient (or any subscriber) GETs it later. This host is only a
// rendezvous peer, not the source of wallet authority.
//
// Identity-gated, append-only, bounded. Only registered nodes (see Onboard.php / node_registry) may
// relay, and every stored message keeps the sender's signature so a reader verifies it end-to-end.
declare(strict_types=1);

require_once __DIR__ . '/Db.php';
require_once __DIR__ . '/Crypto.php';

final class Relay
{
    public const ONLINE_WINDOW_S = 120;     // a node is "online" if it pinged within this window
    public const MAX_BODY_BYTES   = 16384;   // cap a relayed payload (defence against abuse)
    public const MAX_FETCH        = 200;     // cap rows returned per poll
    public const TOPIC_BROADCAST  = '*';     // messages with no specific recipient

    private static function now(): float { return microtime(true); }

    private static function config(): array
    {
        $file = dirname(__DIR__) . '/config.php';
        return is_file($file) ? (array) require $file : [];
    }

    private static function nodeName(): string
    {
        $cfg = self::config();
        $raw = (string) (
            $cfg['node_name']
            ?? $cfg['public_base_url']
            ?? $cfg['public_host']
            ?? ($_SERVER['HTTP_HOST'] ?? 'molgang-php-relay')
        );
        $host = parse_url($raw, PHP_URL_HOST);
        $name = strtolower($host !== false && $host !== null ? $host : $raw);
        $name = preg_replace('~:\d+$~', '', $name) ?? '';
        $name = preg_replace('~[^a-z0-9._-]+~', '-', $name) ?? '';
        $name = trim($name, '.-');
        return $name !== '' ? $name : 'molgang-php-relay';
    }

    /** Is this pubkey a node that completed signed onboarding? (relay is registered-only) */
    private static function isRegistered(string $pubHex): bool
    {
        $row = Db::one('SELECT 1 x FROM node_registry WHERE pubkey=? AND revoked=0', [strtolower($pubHex)]);
        return $row !== null;
    }

    // ---- presence: which knitweb nodes are live -----------------------------

    /**
     * A registered node announces it is alive (heartbeat). Touches last_seen on node_registry.
     * @return array{ok:bool,error?:string,online?:array}
     */
    public static function ping(string $pubHex, ?string $endpoint = null, ?string $region = null,
                                ?string $role = null, ?int $load = null): array
    {
        $pubHex = strtolower(trim($pubHex));
        if (!Crypto::isCompressedPubkey($pubHex)) {
            return ['ok' => false, 'error' => 'bad pubkey'];
        }
        if (!self::isRegistered($pubHex)) {
            return ['ok' => false, 'error' => 'node not registered'];
        }
        // Region/role/load are OPTIONAL self-reported bootstrap hints (#98): a relay
        // announces role='relay' + its region tag + queue depth so bootstrap() can rank it.
        $region = $region !== null ? substr(preg_replace('~[^a-z0-9_-]~', '', strtolower($region)) ?? '', 0, 32) : null;
        $role   = $role === 'relay' ? 'relay' : ($role === 'node' ? 'node' : null);
        Db::run(
            'UPDATE node_registry SET last_seen=?, endpoint=COALESCE(?,endpoint),
                    region=COALESCE(?,region), role=COALESCE(?,role),
                    load_hint=COALESCE(?,load_hint)
              WHERE pubkey=?',
            [self::now(), $endpoint !== null && $endpoint !== '' ? $endpoint : null,
             $region !== null && $region !== '' ? $region : null, $role,
             $load !== null ? max(0, $load) : null, $pubHex]
        );
        return ['ok' => true, 'online' => self::online()];
    }

    /**
     * Region-aware bootstrap roster (#98): registered, non-revoked RELAY rows ranked
     * least-loaded first, then most-recently-seen — so a joining peer seeds its RelayPool
     * with the healthiest relays instead of one hard-coded base. Bounded like online().
     * Optional ?region= pins matching relays to the FRONT (never filters others out —
     * a lone-region peer must still bootstrap through remote relays).
     */
    public static function bootstrap(?string $region = null): array
    {
        $rows = Db::all(
            "SELECT endpoint, region, load_hint, last_seen FROM node_registry
              WHERE revoked=0 AND role='relay' AND endpoint IS NOT NULL AND endpoint <> ''
           ORDER BY load_hint ASC, last_seen DESC
              LIMIT " . self::MAX_FETCH, []
        );
        $now = self::now();
        $relays = [];
        foreach ($rows as $r) {
            $relays[] = [
                'base'   => $r['endpoint'],
                'region' => $r['region'],
                'load'   => (int) $r['load_hint'],
                'age_s'  => round($now - (float) $r['last_seen'], 1),
            ];
        }
        if ($region !== null && $region !== '') {
            // STABLE partition — matching region first, the rest after, each group KEEPING the
            // SQL load_hint/last_seen order. (usort() is not stable, so a comparator that only
            // compares region equality would scramble the ranking within each group.)
            $region = strtolower($region);
            $match = $other = [];
            foreach ($relays as $r) {
                if (strtolower((string) $r['region']) === $region) {
                    $match[] = $r;
                } else {
                    $other[] = $r;
                }
            }
            $relays = array_merge($match, $other);
        }
        return ['relays' => $relays, 'count' => count($relays), 'time' => $now];
    }

    /** The roster of currently-online knitweb nodes (address + endpoint, never the raw pubkey-as-secret). */
    public static function online(): array
    {
        $cutoff = self::now() - self::ONLINE_WINDOW_S;
        $rows = Db::all(
            'SELECT pubkey, address, endpoint, device_fp, last_seen
               FROM node_registry
              WHERE revoked=0 AND last_seen >= ?
           ORDER BY last_seen DESC',
            [$cutoff]
        );
        $now = self::now();
        $out = [];
        foreach ($rows as $r) {
            $out[] = [
                'address'   => $r['address'],
                'pubkey'    => $r['pubkey'],
                'endpoint'  => $r['endpoint'],
                'device_fp' => $r['device_fp'],
                'age_s'     => round($now - (float) $r['last_seen'], 1),
            ];
        }
        return $out;
    }

    // ---- relay: store-and-forward signed knitweb messages -------------------

    /**
     * Accept a message for relay. The sender signs the message body with its knitweb wallet;
     * we verify the signature AND that the sender is a registered node before storing. The
     * stored signature travels with the message so the recipient verifies it independently.
     *
     * @param array $msg { from, to?, topic?, body, sig }
     * @return array{ok:bool,error?:string,id?:string}
     */
    public static function send(array $msg): array
    {
        $from  = strtolower(trim((string) ($msg['from'] ?? '')));
        $to    = trim((string) ($msg['to'] ?? ''));            // pls1 address OR '' (broadcast)
        $topic = trim((string) ($msg['topic'] ?? self::TOPIC_BROADCAST));
        $body  = (string) ($msg['body'] ?? '');
        $sig   = strtolower(trim((string) ($msg['sig'] ?? '')));

        $err = self::checkMessage($from, $to, $topic, $body, $sig);
        if ($err !== null) {
            return ['ok' => false, 'error' => $err];
        }

        $id = bin2hex(random_bytes(12));
        Db::run(
            'INSERT INTO relay_message (id, from_pub, to_addr, topic, body, sig, created)
             VALUES (?,?,?,?,?,?,?)',
            [$id, $from, $to !== '' ? $to : null, $topic, $body, $sig, self::now()]
        );
        // Opportunistically touch presence: a node that relays is clearly alive.
        Db::run('UPDATE node_registry SET last_seen=? WHERE pubkey=?', [self::now(), $from]);
        return ['ok' => true, 'id' => $id];
    }

    /**
     * The full send() gate, shared with reconcile() ingest — a peer relay is never trusted
     * blindly, every reconciled row passes the exact same checks a direct POST would.
     * Returns the error string, or null when the message is acceptable.
     */
    private static function checkMessage(string $from, string $to, string $topic, string $body,
                                         string $sig): ?string
    {
        if (!Crypto::isCompressedPubkey($from)) {
            return 'from must be a compressed secp256k1 pubkey';
        }
        if ($body === '' || strlen($body) > self::MAX_BODY_BYTES) {
            return 'body empty or too large';
        }
        if (!self::isRegistered($from)) {
            return 'sender not a registered node';
        }
        // Signature-gated: the sender must sign exactly what gets relayed (to|topic|body),
        // so a stored message cannot be forged or replayed under another node's identity.
        $signed = self::signedPreimage($to, $topic, $body);
        if (!Crypto::verify($from, $signed, $sig)) {
            return 'invalid signature';
        }
        if ($topic === '' || strlen($topic) > 96) {
            return 'bad topic';
        }
        if ($to !== '' && (strlen($to) > 64 || strncmp($to, Crypto::ADDRESS_HRP, 4) !== 0)) {
            return 'to must be a pls1 address or empty';
        }
        return null;
    }

    /** The exact bytes a sender signs for relay — recompute identically on read to re-verify. */
    public static function signedPreimage(string $to, string $topic, string $body): string
    {
        return "knitweb-relay:v1\n{$to}\n{$topic}\n{$body}";
    }

    // ---- anti-entropy: reconcile with peer relays (#96) ---------------------

    /** Peer relay API bases from config ('relay_peers'), e.g. https://host/molgang/api/relay */
    public static function peers(): array
    {
        $cfg = self::config();
        $out = [];
        foreach ((array) ($cfg['relay_peers'] ?? []) as $p) {
            $p = rtrim(trim((string) $p), '/');
            if ($p !== '' && preg_match('~^https?://~i', $p)) {
                $out[] = $p;
            }
        }
        return array_values(array_unique($out));
    }

    private static function ensurePeerCursorTable(): void
    {
        // Portable across MySQL (VARCHAR key) and the SQLite used in smoke tests.
        Db::run('CREATE TABLE IF NOT EXISTS relay_peer_cursor (
                   peer      VARCHAR(255) NOT NULL PRIMARY KEY,
                   cursor_at DOUBLE       NOT NULL DEFAULT 0,
                   last_sync DOUBLE       NOT NULL DEFAULT 0,
                   last_new  INT          NOT NULL DEFAULT 0
                 )', []);
    }

    /** Default HTTP GET → decoded JSON array (5s timeout); injectable in tests. */
    private static function httpGetJson(string $url): ?array
    {
        $ctx = stream_context_create(['http' => ['timeout' => 5, 'ignore_errors' => true]]);
        $raw = @file_get_contents($url, false, $ctx);
        if ($raw === false) {
            return null;
        }
        $data = json_decode($raw, true);
        return is_array($data) ? $data : null;
    }

    /**
     * Ingest one message fetched FROM A PEER RELAY: same gate as send(), but the peer's
     * message id is KEPT (that id is the cross-relay dedup key — an already-known id is a
     * no-op) while `created` is stamped locally so subscribers' since-cursors still see it.
     * @return array{ok:bool,error?:string,id?:string,known?:bool}
     */
    public static function ingest(array $m): array
    {
        $id = strtolower(trim((string) ($m['id'] ?? '')));
        if (!preg_match('~^[0-9a-f]{8,24}$~', $id)) {    // fits relay_message.id VARCHAR(24)
            return ['ok' => false, 'error' => 'bad message id'];
        }
        if (Db::one('SELECT 1 x FROM relay_message WHERE id=?', [$id]) !== null) {
            return ['ok' => true, 'id' => $id, 'known' => true];    // idempotent replay
        }
        $from  = strtolower(trim((string) ($m['from'] ?? '')));
        $to    = trim((string) ($m['to'] ?? ''));
        $topic = trim((string) ($m['topic'] ?? self::TOPIC_BROADCAST));
        $body  = (string) ($m['body'] ?? '');
        $sig   = strtolower(trim((string) ($m['sig'] ?? '')));
        $err = self::checkMessage($from, $to, $topic, $body, $sig);
        if ($err !== null) {
            return ['ok' => false, 'error' => $err];
        }
        Db::run(
            'INSERT INTO relay_message (id, from_pub, to_addr, topic, body, sig, created)
             VALUES (?,?,?,?,?,?,?)',
            [$id, $from, $to !== '' ? $to : null, $topic, $body, $sig, self::now()]
        );
        return ['ok' => true, 'id' => $id, 'known' => false];
    }

    /**
     * One anti-entropy pass: for every peer relay, GET …/fetch?since=<per-peer cursor> and
     * ingest anything new through the full send() gate. Incremental (the peer's returned
     * cursor is persisted per peer) and idempotent (dedup by message id). Request-driven and
     * bounded (≤ MAX_FETCH rows per peer per pass) — shared-hosting-safe like the rest of
     * this node; drive it from cron / desktop_bridge / the ?op=reconcile hook.
     *
     * @param ?array    $peers override the configured peer list (tests)
     * @param ?callable $http  fn(string $url): ?array — override the HTTP GET (tests)
     */
    public static function reconcile(?array $peers = null, ?callable $http = null): array
    {
        self::ensurePeerCursorTable();
        $peers = $peers ?? self::peers();
        $http  = $http ?? [self::class, 'httpGetJson'];
        $report = [];
        foreach ($peers as $peer) {
            $row = Db::one('SELECT cursor_at FROM relay_peer_cursor WHERE peer=?', [$peer]);
            $since = $row !== null ? (float) $row['cursor_at'] : 0.0;
            $resp = $http($peer . '/fetch?' . http_build_query(['since' => $since,
                                                               'limit' => self::MAX_FETCH]));
            if (!is_array($resp) || !isset($resp['messages']) || !is_array($resp['messages'])) {
                $report[] = ['peer' => $peer, 'ok' => false, 'error' => 'peer unreachable or bad response'];
                continue;
            }
            $new = $known = $rejected = 0;
            foreach ($resp['messages'] as $m) {
                if (!is_array($m)) {
                    $rejected++;
                    continue;
                }
                $res = self::ingest($m);
                if (!empty($res['ok'])) {
                    empty($res['known']) ? $new++ : $known++;
                } else {
                    $rejected++;
                }
            }
            $cursor = max($since, (float) ($resp['cursor'] ?? $since));
            Db::run('DELETE FROM relay_peer_cursor WHERE peer=?', [$peer]);
            Db::run('INSERT INTO relay_peer_cursor (peer, cursor_at, last_sync, last_new)
                     VALUES (?,?,?,?)', [$peer, $cursor, self::now(), $new]);
            $report[] = ['peer' => $peer, 'ok' => true, 'new' => $new, 'known' => $known,
                         'rejected' => $rejected, 'cursor' => $cursor,
                         'scanned' => count($resp['messages'])];
        }
        return ['ok' => true, 'peers' => $report, 'time' => self::now()];
    }

    /**
     * Poll for messages. A node fetches broadcasts + anything addressed to its pls1 address,
     * newer than the cursor it last saw. Read is open (messages are signed, content is its own
     * authorization) but never returns more than MAX_FETCH rows.
     *
     * @param array $q { to?, topic?, since?, limit? }
     */
    public static function fetch(array $q): array
    {
        $to    = trim((string) ($q['to'] ?? ''));
        $topic = trim((string) ($q['topic'] ?? ''));
        $since = (float) ($q['since'] ?? 0);
        $limit = max(1, min(self::MAX_FETCH, (int) ($q['limit'] ?? self::MAX_FETCH)));

        $sql  = 'SELECT id, from_pub, to_addr, topic, body, sig, created FROM relay_message WHERE created > ?';
        $args = [$since];
        if ($to !== '') {
            // broadcasts (to_addr IS NULL) OR messages addressed to this node
            $sql .= ' AND (to_addr IS NULL OR to_addr = ?)';
            $args[] = $to;
        }
        if ($topic !== '') {
            $sql .= ' AND topic = ?';
            $args[] = $topic;
        }
        $sql .= ' ORDER BY created ASC LIMIT ' . $limit;
        $rows = Db::all($sql, $args);

        $cursor = $since;
        $msgs = [];
        foreach ($rows as $r) {
            $cursor = max($cursor, (float) $r['created']);
            $msgs[] = [
                'id'      => $r['id'],
                'from'    => $r['from_pub'],
                'to'      => $r['to_addr'],
                'topic'   => $r['topic'],
                'body'    => $r['body'],
                'sig'     => $r['sig'],          // recipient re-verifies with signedPreimage()
                'created' => (float) $r['created'],
            ];
        }
        return ['messages' => $msgs, 'cursor' => $cursor, 'count' => count($msgs)];
    }

    /** A small public health/identity card for the relay node itself. */
    public static function info(): array
    {
        $nodes  = (int) (Db::one('SELECT COUNT(*) c FROM node_registry WHERE revoked=0')['c'] ?? 0);
        $online = self::online();
        $queued = (int) (Db::one('SELECT COUNT(*) c FROM relay_message')['c'] ?? 0);
        return [
            'node'        => self::nodeName(),
            'relays'      => self::bootstrap()['relays'],   // cross-region roster (#98)
            'role'        => 'knitweb HTTP relay + presence (request-driven, host-neutral PHP)',
            'transport'   => 'https',
            'scheme'      => 'secp256k1-ecdsa-sha256',
            'nodes'       => $nodes,
            'online'      => count($online),
            'online_list' => $online,
            'queued'      => $queued,
            'time'        => self::now(),
        ];
    }
}
