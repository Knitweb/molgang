-- MOLGANG dapp — MySQL schema. Apply once to the database (e.g. 5martm_ED):
--   mysql -h HOST -u USER -p DBNAME < schema.sql
-- All state is request-driven (no long-lived process), so this runs on plain shared hosting.

CREATE TABLE IF NOT EXISTS player (
  device_id   VARCHAR(96)  NOT NULL PRIMARY KEY,   -- stable per-device id (browser localStorage / desktop)
  name        VARCHAR(48)  NOT NULL,
  avatar      VARCHAR(32)  NOT NULL,
  address     VARCHAR(64)  NOT NULL,               -- deterministic pls1… wallet derived from device_id
  pulses      INT          NOT NULL DEFAULT 50,    -- FAUCET_PULSES
  silk        INT          NOT NULL DEFAULT 10,    -- FAUCET_SILK
  xp          INT          NOT NULL DEFAULT 0,
  is_bot      TINYINT      NOT NULL DEFAULT 0,
  created     DOUBLE       NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS session (
  sid         VARCHAR(40)  NOT NULL PRIMARY KEY,
  device_id   VARCHAR(96)  NOT NULL,
  table_id    VARCHAR(24)  NULL,
  last_seen   DOUBLE       NOT NULL,
  KEY k_dev (device_id), KEY k_table (table_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS proposal (
  pid         VARCHAR(40)  NOT NULL PRIMARY KEY,
  table_id    VARCHAR(24)  NOT NULL,
  proposer    VARCHAR(96)  NOT NULL,               -- device_id of the proposer
  by_name     VARCHAR(48)  NOT NULL,
  term        VARCHAR(160) NOT NULL,
  kind        VARCHAR(8)   NOT NULL,               -- 'term' | 'link'
  subject     VARCHAR(96)  NULL,
  relation    VARCHAR(24)  NULL,
  obj         VARCHAR(96)  NULL,
  topic       VARCHAR(96)  NOT NULL,
  settled     TINYINT      NOT NULL DEFAULT 0,
  outcome     VARCHAR(16)  NULL,                   -- 'confirmed' | 'mismatch'
  woven       TINYINT      NOT NULL DEFAULT 0,
  fiber_cid   VARCHAR(80)  NULL,
  is_chem     TINYINT      NOT NULL DEFAULT 0,
  created     DOUBLE       NOT NULL,
  KEY k_table (table_id), KEY k_topic (topic), KEY k_woven (woven)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS vote (
  pid         VARCHAR(40)  NOT NULL,
  voter       VARCHAR(96)  NOT NULL,               -- device_id (or bot id)
  verdict     VARCHAR(10)  NOT NULL,               -- 'confirm' | 'mismatch' | 'abstain'
  created     DOUBLE       NOT NULL,
  PRIMARY KEY (pid, voter)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Cross-client presence: the web dapp and the desktop client both beat here, keyed by the
-- shared device→wallet identity, so each can see whether the other is active or was used before.
CREATE TABLE IF NOT EXISTS presence (
  device_id   VARCHAR(96)  NOT NULL,
  client      VARCHAR(10)  NOT NULL,               -- 'web' | 'desktop'
  last_seen   DOUBLE       NOT NULL,
  first_seen  DOUBLE       NOT NULL,
  info        VARCHAR(160) NULL,                   -- e.g. desktop version / host
  PRIMARY KEY (device_id, client)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Email subscribers for daily digest (refs #76).
-- Email is stored as AES-256-CBC ciphertext + IV (never plaintext).
-- email_hmac is a UNIQUE constraint to detect duplicates and enforce idempotence.
CREATE TABLE IF NOT EXISTS subscriber (
  device_id   VARCHAR(96)  NOT NULL PRIMARY KEY,   -- player's device ID
  email_enc   LONGBLOB     NOT NULL,               -- email encrypted with AES-256-CBC, stored as binary
  iv_hex      VARCHAR(32)  NOT NULL,               -- IV (16 bytes) in hex
  email_hmac  VARCHAR(64)  NOT NULL UNIQUE,        -- HMAC-SHA256 of normalized email (for duplicate detection)
  created     DOUBLE       NOT NULL,
  KEY k_hash (email_hmac)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
