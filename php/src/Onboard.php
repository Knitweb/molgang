<?php
// Onboard — wallet-signed QR onboarding of a new p2p node into the owner's DB (Refs #63).
//
// Flow (challenge–response, signature-gated):
//   1. New node GETs  /api/onboard/challenge        → { challenge, expires, endpoint, qr }
//      The QR encodes the challenge + this relay's submit URL, so a phone/desktop wallet can scan it.
//   2. Node SIGNS the challenge with its knitweb wallet (secp256k1) and POSTs
//      /api/onboard/register { pubkey, sig, device_fp, endpoint? }.
//   3. The server VERIFIES the signature against the challenge. ONLY on a valid signature does it
//      INSERT (pubkey, derived pls1 address, device_fp) into node_registry. Invalid/missing/expired/
//      reused signatures are REJECTED. This is authenticated onboarding to the owner's own DB —
//      never an unauthenticated write, never a backdoor.
//
// Challenges are HMAC-stamped & time-boxed (stateless: we don't need a row to issue one) and, once a
// signature is accepted, the challenge is burned in node_challenge so it can't be replayed.
declare(strict_types=1);

require_once __DIR__ . '/Db.php';
require_once __DIR__ . '/Crypto.php';

final class Onboard
{
    public const CHALLENGE_TTL_S = 600;     // a challenge is valid for 10 minutes
    public const NONCE_BYTES     = 18;

    private static function now(): int { return time(); }

    /** A per-host secret used to stamp challenges (so we can issue them statelessly). */
    private static function secret(): string
    {
        $cfg = self::config();
        if (!empty($cfg['onboard_secret'])) {
            return (string) $cfg['onboard_secret'];
        }
        // Fallback: derive a stable secret from the DB password so it survives restarts without
        // extra config. (Set 'onboard_secret' in config.php to rotate independently.)
        return hash('sha256', 'knitweb-onboard:' . ($cfg['pass'] ?? '') . ':' . ($cfg['name'] ?? ''));
    }

    private static function config(): array
    {
        $file = dirname(__DIR__) . '/config.php';
        return is_file($file) ? (array) require $file : [];
    }

    /** The public submit endpoint, derived from the current request (works under any base path). */
    private static function endpointUrl(): string
    {
        $https = (($_SERVER['HTTPS'] ?? '') !== '' && ($_SERVER['HTTPS'] ?? 'off') !== 'off')
            || (($_SERVER['SERVER_PORT'] ?? '') === '443')
            || (($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '') === 'https');
        $scheme = $https ? 'https' : 'http';
        $host   = $_SERVER['HTTP_HOST'] ?? '5mart.ml';
        // strip "/api/..." back to the dapp base, then append the canonical register route
        $uri  = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?? '/';
        $base = preg_replace('~/api/.*$~', '', $uri);
        $base = rtrim((string) $base, '/');
        return "{$scheme}://{$host}{$base}/api/onboard/register";
    }

    // ---- 1) issue a challenge ----------------------------------------------

    /**
     * Issue a fresh, time-boxed challenge. Stateless: challenge = "<nonce>.<exp>.<hmac>".
     * @return array challenge + endpoint + a QR payload (and a QR image URL hint)
     */
    public static function challenge(): array
    {
        $nonce = bin2hex(random_bytes(self::NONCE_BYTES));
        $exp   = self::now() + self::CHALLENGE_TTL_S;
        $body  = "knitweb-onboard:5mart.ml:{$nonce}:{$exp}";
        $mac   = hash_hmac('sha256', $body, self::secret());
        $challenge = "{$body}:{$mac}";
        $endpoint  = self::endpointUrl();

        // The QR encodes everything a wallet needs to sign & submit, as a compact URI.
        $qr = 'knitweb://onboard?'
            . 'endpoint=' . rawurlencode($endpoint)
            . '&challenge=' . rawurlencode($challenge);

        return [
            'challenge' => $challenge,
            'expires'   => $exp,
            'ttl_s'     => self::CHALLENGE_TTL_S,
            'endpoint'  => $endpoint,
            'scheme'    => 'secp256k1-ecdsa-sha256',
            'qr'        => $qr,
            // A self-contained image URL (Google Chart QR) so the page can render it with no JS libs.
            'qr_image'  => 'https://api.qrserver.com/v1/create-qr-code/?size=240x240&data=' . rawurlencode($qr),
            'instructions' => 'Sign the EXACT "challenge" string with your knitweb wallet '
                . '(secp256k1 / DER hex), then POST {pubkey, sig, device_fp} to "endpoint".',
        ];
    }

    /** Validate a challenge's HMAC + expiry without touching the DB. */
    private static function challengeValid(string $challenge): bool
    {
        $parts = explode(':', $challenge);
        if (count($parts) !== 5) {
            return false;
        }
        // parts: knitweb-onboard, 5mart.ml, <nonce>, <exp>, <mac>
        [$tag, $host, $nonce, $exp, $mac] = $parts;
        if ($tag !== 'knitweb-onboard' || $host !== '5mart.ml' || !ctype_xdigit($nonce) || !ctype_digit($exp)) {
            return false;
        }
        if ((int) $exp < self::now()) {
            return false;   // expired
        }
        $body = "{$tag}:{$host}:{$nonce}:{$exp}";
        $expect = hash_hmac('sha256', $body, self::secret());
        return hash_equals($expect, $mac);
    }

    // ---- 2/3) verify the signature & register ------------------------------

    /**
     * Register a node — SIGNATURE-GATED. Inserts into node_registry ONLY on a valid signature
     * over a valid, unused, unexpired challenge.
     *
     * @param array $body { pubkey, sig, device_fp, challenge, endpoint? }
     * @return array{ok:bool,error?:string,...}
     */
    public static function register(array $body): array
    {
        $pubHex    = strtolower(trim((string) ($body['pubkey'] ?? '')));
        $sigHex    = strtolower(trim((string) ($body['sig'] ?? '')));
        $deviceFp  = trim((string) ($body['device_fp'] ?? ''));   // node-supplied MAC/device fingerprint
        $challenge = (string) ($body['challenge'] ?? '');
        $endpoint  = trim((string) ($body['endpoint'] ?? ''));

        // --- hard input gates (reject BEFORE any DB consideration) ----------
        if (!Crypto::isCompressedPubkey($pubHex)) {
            return ['ok' => false, 'error' => 'pubkey must be a 33-byte compressed secp256k1 hex'];
        }
        if (!Crypto::isHex($sigHex)) {
            return ['ok' => false, 'error' => 'sig must be DER-encoded hex'];
        }
        if ($deviceFp === '' || strlen($deviceFp) > 128) {
            return ['ok' => false, 'error' => 'device_fp (device/MAC fingerprint) required'];
        }
        if (!self::challengeValid($challenge)) {
            return ['ok' => false, 'error' => 'challenge invalid or expired — request a new one'];
        }
        if ($endpoint !== '' && (strlen($endpoint) > 255 || !preg_match('~^https?://~i', $endpoint))) {
            return ['ok' => false, 'error' => 'endpoint must be an http(s) URL'];
        }

        // --- THE GATE: verify the wallet signature over the challenge -------
        if (!Crypto::verify($pubHex, $challenge, $sigHex)) {
            return ['ok' => false, 'error' => 'signature does not verify for this pubkey + challenge'];
        }

        // --- one-time use: burn the challenge (anti-replay) -----------------
        $cid = hash('sha256', $challenge);
        if (Db::one('SELECT 1 x FROM node_challenge WHERE challenge_id=?', [$cid]) !== null) {
            return ['ok' => false, 'error' => 'challenge already used'];
        }
        Db::run('INSERT INTO node_challenge (challenge_id, used) VALUES (?,?)', [$cid, self::now()]);

        // --- the signature-gated WRITE: upsert into node_registry ----------
        $address = Crypto::addressFromPubkey($pubHex);
        $now = microtime(true);
        $existing = Db::one('SELECT pubkey FROM node_registry WHERE pubkey=?', [$pubHex]);
        if ($existing === null) {
            Db::run(
                'INSERT INTO node_registry (pubkey, address, device_fp, endpoint, registered, last_seen, revoked)
                 VALUES (?,?,?,?,?,?,0)',
                [$pubHex, $address, $deviceFp, $endpoint !== '' ? $endpoint : null, $now, $now]
            );
            $status = 'registered';
        } else {
            // Re-onboard from a (possibly new) device: refresh fingerprint/endpoint, keep identity.
            Db::run(
                'UPDATE node_registry SET device_fp=?, endpoint=COALESCE(?,endpoint), last_seen=?, revoked=0 WHERE pubkey=?',
                [$deviceFp, $endpoint !== '' ? $endpoint : null, $now, $pubHex]
            );
            $status = 're-registered';
        }

        return [
            'ok'      => true,
            'status'  => $status,
            'address' => $address,
            'pubkey'  => $pubHex,
            'message' => 'node onboarded — you may now POST /api/relay/send and /api/relay/ping',
        ];
    }

    /** Public, read-only view of a registered node by address (no secrets). */
    public static function lookup(string $address): array
    {
        $r = Db::one('SELECT address, pubkey, endpoint, registered, last_seen, revoked FROM node_registry WHERE address=?', [$address]);
        if ($r === null) {
            return ['found' => false];
        }
        return [
            'found'      => true,
            'address'    => $r['address'],
            'pubkey'     => $r['pubkey'],
            'endpoint'   => $r['endpoint'],
            'registered' => (float) $r['registered'],
            'last_seen'  => (float) $r['last_seen'],
            'revoked'    => (bool) $r['revoked'],
        ];
    }
}
