<?php
// Relay — 5mart.ml as an always-on HTTP relay + presence node for the knitweb (Refs #61).
//
// WHY HTTP and not raw p2p: this is shared hosting. A process here CAN bind a local socket, but a
// perimeter firewall drops all inbound TCP from the internet (verified — see php/PORTCHECK.md / #62),
// so a listening peer is unreachable. The always-on transport that IS reachable is nginx → PHP over
// HTTPS. So peers reach each other request-driven: a node POSTs a (signed) message here, the relay
// stores it in MySQL, and the recipient (or any subscriber) GETs it later. 5mart.ml is the rendezvous.
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
    public static function ping(string $pubHex, ?string $endpoint = null): array
    {
        $pubHex = strtolower(trim($pubHex));
        if (!Crypto::isCompressedPubkey($pubHex)) {
            return ['ok' => false, 'error' => 'bad pubkey'];
        }
        if (!self::isRegistered($pubHex)) {
            return ['ok' => false, 'error' => 'node not registered'];
        }
        Db::run(
            'UPDATE node_registry SET last_seen=?, endpoint=COALESCE(?,endpoint) WHERE pubkey=?',
            [self::now(), $endpoint !== null && $endpoint !== '' ? $endpoint : null, $pubHex]
        );
        return ['ok' => true, 'online' => self::online()];
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

        if (!Crypto::isCompressedPubkey($from)) {
            return ['ok' => false, 'error' => 'from must be a compressed secp256k1 pubkey'];
        }
        if ($body === '' || strlen($body) > self::MAX_BODY_BYTES) {
            return ['ok' => false, 'error' => 'body empty or too large'];
        }
        if (!self::isRegistered($from)) {
            return ['ok' => false, 'error' => 'sender not a registered node'];
        }
        // Signature-gated: the sender must sign exactly what gets relayed (to|topic|body),
        // so a stored message cannot be forged or replayed under another node's identity.
        $signed = self::signedPreimage($to, $topic, $body);
        if (!Crypto::verify($from, $signed, $sig)) {
            return ['ok' => false, 'error' => 'invalid signature'];
        }
        if ($topic === '' || strlen($topic) > 96) {
            return ['ok' => false, 'error' => 'bad topic'];
        }
        if ($to !== '' && (strlen($to) > 64 || strncmp($to, Crypto::ADDRESS_HRP, 4) !== 0)) {
            return ['ok' => false, 'error' => 'to must be a pls1 address or empty'];
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

    /** The exact bytes a sender signs for relay — recompute identically on read to re-verify. */
    public static function signedPreimage(string $to, string $topic, string $body): string
    {
        return "knitweb-relay:v1\n{$to}\n{$topic}\n{$body}";
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
            'node'        => '5mart.ml',
            'role'        => 'knitweb HTTP relay + presence (request-driven, always-on via nginx)',
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
