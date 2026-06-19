<?php
// Crypto — a tiny PHP mirror of knitweb.core.crypto's verify path (secp256k1 / ECDSA / SHA-256).
//
// The knitweb wallet (github.com/knitweb/pulse, src/knitweb/core/crypto.py) signs with:
//   * curve     : secp256k1
//   * hash      : SHA-256
//   * signature : ECDSA over sha256(message), DER-encoded, hex
//   * public key: 33-byte COMPRESSED SEC1 point, hex
//   * address   : "pls1" + base32_lower_nopad( scheme_byte(0x00) || sha256(sha256(pubkey))[:20] )
//
// We verify those signatures with PHP's bundled OpenSSL. The only non-obvious step is turning a
// raw 33-byte compressed point into something openssl can load: we wrap it in a SubjectPublicKeyInfo
// (id-ecPublicKey + the secp256k1 named-curve OID) DER and PEM-encode it. OpenSSL 3 (PHP 8.1 here)
// parses compressed points directly, so NO manual point decompression / GMP is needed.
//
// This is verify-ONLY: the server never holds a private key. A valid signature over a
// server-issued challenge is the sole gate to a DB write (see Onboard.php).
declare(strict_types=1);

final class Crypto
{
    public const ADDRESS_HRP = 'pls1';
    public const SCHEME_SECP256K1_ECDSA = 0;   // the only blessed scheme (mirrors KNOWN_SCHEMES)

    // ---- public key handling -----------------------------------------------

    /** True iff $hex is valid hex of exactly $nBytes bytes (when given). */
    public static function isHex(string $hex, ?int $nBytes = null): bool
    {
        if ($hex === '' || strlen($hex) % 2 !== 0 || !ctype_xdigit($hex)) {
            return false;
        }
        return $nBytes === null || strlen($hex) === $nBytes * 2;
    }

    /** A compressed secp256k1 pubkey is 33 bytes: a 0x02/0x03 prefix + 32-byte X. */
    public static function isCompressedPubkey(string $pubHex): bool
    {
        if (!self::isHex($pubHex, 33)) {
            return false;
        }
        $prefix = substr($pubHex, 0, 2);
        return $prefix === '02' || $prefix === '03';
    }

    // ---- signature verification --------------------------------------------

    /**
     * Verify a knitweb wallet signature.
     *
     * @param string $pubHex    33-byte compressed secp256k1 public key, hex.
     * @param string $message   the exact bytes that were signed (e.g. the challenge string).
     * @param string $sigHex    DER-encoded ECDSA signature, hex.
     * @return bool true ONLY for a cryptographically valid signature.
     */
    public static function verify(string $pubHex, string $message, string $sigHex): bool
    {
        $pubHex = strtolower(trim($pubHex));
        $sigHex = strtolower(trim($sigHex));
        if (!self::isCompressedPubkey($pubHex) || !self::isHex($sigHex)) {
            return false;
        }
        $pem = self::spkiPemFromPoint(hex2bin($pubHex));
        $key = openssl_pkey_get_public($pem);
        if ($key === false) {
            return false;
        }
        // OPENSSL_ALGO_SHA256 makes OpenSSL hash $message with SHA-256 and ECDSA-verify the digest —
        // identical to knitweb signing the prehashed sha256(message). 1 = valid, 0 = invalid, -1 = error.
        $ok = openssl_verify($message, hex2bin($sigHex), $key, OPENSSL_ALGO_SHA256);
        return $ok === 1;
    }

    // ---- address derivation (must byte-match knitweb.core.crypto.address) ---

    /** Derive the canonical pls1 address from a compressed pubkey hex (scheme 0 = secp256k1). */
    public static function addressFromPubkey(string $pubHex): string
    {
        $pub = hex2bin(strtolower(trim($pubHex)));
        $fingerprint = substr(hash('sha256', hash('sha256', $pub, true), true), 0, 20);
        $payload = chr(self::SCHEME_SECP256K1_ECDSA) . $fingerprint;
        return self::ADDRESS_HRP . self::base32LowerNoPad($payload);
    }

    // ---- internals ----------------------------------------------------------

    /** Wrap a SEC1 point (compressed or uncompressed) in a SubjectPublicKeyInfo PEM. */
    private static function spkiPemFromPoint(string $point): string
    {
        // AlgorithmIdentifier = SEQUENCE { id-ecPublicKey (1.2.840.10045.2.1), secp256k1 (1.3.132.0.10) }
        $alg = self::derSeq(
            self::derOid('2a8648ce3d0201') . self::derOid('2b8104000a')
        );
        // SubjectPublicKeyInfo = SEQUENCE { AlgorithmIdentifier, BIT STRING(point) }
        $spki = self::derSeq($alg . self::derBitString($point));
        return "-----BEGIN PUBLIC KEY-----\n"
            . chunk_split(base64_encode($spki), 64, "\n")
            . "-----END PUBLIC KEY-----\n";
    }

    private static function derLen(int $n): string
    {
        if ($n < 0x80) {
            return chr($n);
        }
        $bytes = '';
        while ($n > 0) {
            $bytes = chr($n & 0xff) . $bytes;
            $n >>= 8;
        }
        return chr(0x80 | strlen($bytes)) . $bytes;
    }

    private static function derSeq(string $body): string
    {
        return "\x30" . self::derLen(strlen($body)) . $body;
    }

    private static function derBitString(string $body): string
    {
        // leading 0x00 = "no unused bits"
        return "\x03" . self::derLen(strlen($body) + 1) . "\x00" . $body;
    }

    private static function derOid(string $bodyHex): string
    {
        $body = hex2bin($bodyHex);
        return "\x06" . self::derLen(strlen($body)) . $body;
    }

    /** RFC4648 base32, lowercase, no '=' padding — matches python base64.b32encode(...).lower().rstrip("="). */
    private static function base32LowerNoPad(string $bytes): string
    {
        $alpha = 'abcdefghijklmnopqrstuvwxyz234567';
        $bits = '';
        foreach (str_split($bytes) as $c) {
            $bits .= str_pad(decbin(ord($c)), 8, '0', STR_PAD_LEFT);
        }
        $out = '';
        foreach (str_split($bits, 5) as $chunk) {
            if (strlen($chunk) < 5) {
                $chunk = str_pad($chunk, 5, '0', STR_PAD_RIGHT);
            }
            $out .= $alpha[bindec($chunk)];
        }
        return $out;
    }
}
