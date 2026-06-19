-- knitweb relay + signed onboarding — ADDITIVE schema (Refs #61 #62 #63).
-- Apply ALONGSIDE schema.sql; it only ADDs tables, it never alters existing ones:
--   mysql -h HOST -u USER -p DBNAME < node_registry.sql
-- All writes to node_registry are signature-gated (see src/Onboard.php) — never an
-- unauthenticated insert. Everything stays request-driven for plain shared hosting.

-- A p2p node's verified identity. A row exists ONLY because the node proved control of its
-- knitweb wallet by signing a server challenge (secp256k1 / the knitweb.core.crypto scheme).
CREATE TABLE IF NOT EXISTS node_registry (
  pubkey      VARCHAR(66)  NOT NULL PRIMARY KEY,   -- 33-byte compressed secp256k1 pubkey, hex (66 chars)
  address     VARCHAR(64)  NOT NULL,               -- derived pls1… address (== knitweb.core.crypto.address)
  device_fp   VARCHAR(128) NOT NULL,               -- node-supplied device/MAC fingerprint
  endpoint    VARCHAR(255) NULL,                   -- optional callback URL the node advertises
  registered  DOUBLE       NOT NULL,               -- first onboarded (unix float)
  last_seen   DOUBLE       NOT NULL,               -- last ping/relay (drives the "online" roster)
  revoked     TINYINT      NOT NULL DEFAULT 0,     -- soft-revoke without deleting history
  UNIQUE KEY k_addr (address),
  KEY k_seen (last_seen),
  KEY k_revoked (revoked)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Burned onboarding challenges — one-time use, so a captured signature can't be replayed.
CREATE TABLE IF NOT EXISTS node_challenge (
  challenge_id  VARCHAR(64) NOT NULL PRIMARY KEY,  -- sha256(challenge), hex
  used          INT         NOT NULL               -- unix time the challenge was consumed
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Store-and-forward relay queue: signed knitweb messages peers exchange THROUGH 5mart.ml over HTTPS.
-- Each row carries the sender's signature, so a reader verifies the message end-to-end (relay is dumb).
CREATE TABLE IF NOT EXISTS relay_message (
  id          VARCHAR(24)  NOT NULL PRIMARY KEY,   -- random message id (hex)
  from_pub    VARCHAR(66)  NOT NULL,               -- sender compressed pubkey hex (must be registered)
  to_addr     VARCHAR(64)  NULL,                   -- recipient pls1 address, or NULL = broadcast
  topic       VARCHAR(96)  NOT NULL,               -- channel/topic ('*' = broadcast)
  body        MEDIUMTEXT   NOT NULL,               -- the relayed payload (signed)
  sig         VARCHAR(160) NOT NULL,               -- DER sig hex over signedPreimage(to,topic,body)
  created     DOUBLE       NOT NULL,               -- unix float; the poll cursor
  KEY k_to (to_addr), KEY k_topic (topic), KEY k_created (created), KEY k_from (from_pub)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
