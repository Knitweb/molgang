<?php
// Copy this to php/config.php on the host and fill in the real MySQL credentials.
// config.php is gitignored and is NEVER committed (and is blocked from HTTP by .htaccess).
return [
    'host' => 'localhost',          // TransIP shared hosting: usually 'localhost'
    'name' => 'YOUR_DB_NAME',       // e.g. 5martm_ED
    'user' => 'YOUR_DB_USER',       // e.g. 5martm_develuse
    'pass' => 'YOUR_DB_PASSWORD',   // set on the host only — keep out of git

    // Optional (Refs #63): a secret that stamps onboarding challenges so they can be issued
    // statelessly. If omitted, one is derived from the DB password+name. Set it to rotate
    // the challenge secret independently of the DB password.
    // 'onboard_secret' => 'a-long-random-string',

    // Optional host-neutral public identity for this relay install. If omitted, the PHP
    // node derives these from the current request host, so a fork/self-host does not
    // inherit 5mart.ml as a hidden default.
    // 'public_base_url' => 'https://example.org/molgang',
    // 'node_name' => 'example.org',

    // Optional (#96): peer relays this node reconciles with (anti-entropy). Each entry is a
    // peer's relay API base; a cron/bridge-driven GET /api/relay/reconcile pulls anything new
    // from every peer through the full send() signature gate. Leave empty for an island relay.
    // 'relay_peers' => ['https://knitweb.art/molgang/api/relay'],

    // Optional (#96): when set, /api/relay/reconcile requires ?key=<this value> — keeps a
    // public flash crowd from spending this node's outbound requests. Cron example:
    //   curl -s 'https://example.org/molgang/api/relay/reconcile?key=SECRET'
    // 'reconcile_secret' => 'another-long-random-string',
];
