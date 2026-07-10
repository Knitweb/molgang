<?php
// MOLGANG dapp — front controller. Serves the JSON API; Apache serves the static SPA
// (index.html / app.js / style.css / avatars) directly via .htaccess. Request-driven:
// every call is a fresh PHP process, so it runs on plain shared hosting (no daemon).
declare(strict_types=1);

require_once __DIR__ . '/../src/Bar.php';
require_once __DIR__ . '/../src/Relay.php';     // knitweb HTTP relay + presence node (Refs #61)
require_once __DIR__ . '/../src/Onboard.php';   // wallet-signed QR node onboarding (Refs #63)
require_once __DIR__ . '/../src/Monitor.php';   // read-only health lens for monitor.html (Refs #59 #60)
require_once __DIR__ . '/../src/Subscribe.php'; // email subscription for daily digest (Refs #76)

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

// route = the path segment(s) after "/api/" (works under any base, e.g. /molgang/).
// Captures a top-level route plus an optional sub-route, e.g. /api/onboard/challenge.
$uri = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?? '/';
$route = preg_match('~/api/([a-z\-]+)~', $uri, $m) ? $m[1] : '';
$sub   = preg_match('~/api/[a-z\-]+/([a-z\-]+)~', $uri, $m2) ? $m2[1] : '';
$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';

$body = [];
if ($method === 'POST') {
    $raw = file_get_contents('php://input') ?: '';
    $body = json_decode($raw, true) ?: [];
}
$q = $_GET;

function out($data): void { echo json_encode($data, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE); exit; }

try {
    switch ($route) {
        case 'version':
            // /api/version — contract drift check (Sprint 3 #58, docs/API.md). The PHP node is a
            // thin client/projection of the canonical Python bar; it speaks the same api_version.
            out(['api_version' => '1', 'engine' => 'php', 'molgang' => '0.1.0',
                 'knitweb' => 'n/a (thin client)', 'knitweb_requirement' => 'n/a (thin client)',
                 'knitweb_compatibility' => [
                     'status' => 'pass',
                     'compatible' => true,
                     'resolved' => 'n/a (thin client)',
                     'requirement' => 'n/a (thin client)',
                     'message' => 'PHP is a thin projection; Python peers advertise runtime knitweb compatibility.',
                 ]]);

        case 'state':
            out(Bar::state(isset($q['sid']) ? (string) $q['sid'] : null));

        case 'join':
            out(Bar::join((string) ($body['name'] ?? 'guest'), $body['avatar'] ?? null, (string) ($body['device'] ?? '')));

        case 'sit':
            out(Bar::sit((string) ($body['sid'] ?? ''), (string) ($body['table'] ?? '')));

        case 'propose':
            out(Bar::propose((string) ($body['sid'] ?? ''), (string) ($body['term'] ?? '')));

        case 'vote':
            out(Bar::vote((string) ($body['sid'] ?? ''), (string) ($body['pid'] ?? ''), (string) ($body['verdict'] ?? '')));

        case 'web':
            out(Bar::web());

        case 'monitor':
            // /api/monitor — read-only health snapshot backing public/monitor.html (Refs #59 #60).
            out(Monitor::summary());

        case 'graph':
            out(Bar::graph($q));

        case 'suggested':
            out(['terms' => Chemistry::suggestedTerms()]);

        case 'device':
            $id = (string) ($q['id'] ?? '');
            out(['registered' => $id !== '', 'wallet' => $id !== '' ? Bar::address($id) : null]);

        case 'presence':
            // Cross-client awareness. The desktop client POSTs its heartbeat here; either
            // client GETs to see whether the other is active or was used before.
            if ($method === 'POST') {
                $dev = (string) ($body['device'] ?? '');
                if ($dev === '') out(['error' => 'device required']);
                Bar::beat($dev, (string) ($body['client'] ?? 'desktop'), $body['info'] ?? null);
                out(['ok' => true, 'peers' => Bar::presenceFor($dev)]);
            }
            $dev = (string) ($q['device'] ?? '');
            out($dev === '' ? ['error' => 'device required'] : ['peers' => Bar::presenceFor($dev)]);

        // ---- email subscription for daily digest (#76) ----------------------
        case 'subscribe':
            if ($method !== 'POST') { http_response_code(405); out(['error' => 'POST required']); }
            $res = Subscribe::subscribe((string) ($body['device'] ?? ''), (string) ($body['email'] ?? ''));
            if (empty($res['ok'])) http_response_code(400);
            out($res);

        // ---- knitweb p2p node: signed onboarding (#63) ----------------------
        case 'onboard':
            // GET  /api/onboard/challenge  → issue a challenge + QR (encodes challenge + submit URL)
            // POST /api/onboard/register   → verify the wallet signature, then (and only then) write
            // GET  /api/onboard/lookup?address=pls1…  → public read-only node card
            if ($sub === 'challenge') {
                out(Onboard::challenge());
            }
            if ($sub === 'register') {
                if ($method !== 'POST') { http_response_code(405); out(['error' => 'POST required']); }
                $res = Onboard::register($body);
                if (empty($res['ok'])) http_response_code(400);   // signature-gated: reject = 400
                out($res);
            }
            if ($sub === 'lookup') {
                out(Onboard::lookup((string) ($q['address'] ?? '')));
            }
            http_response_code(404);
            out(['error' => 'unknown onboard route']);

        // ---- knitweb p2p node: HTTP relay + presence (#61) ------------------
        case 'relay':
            // GET  /api/relay/info                         → node health/identity card
            // GET  /api/relay/online                       → roster of live nodes
            // POST /api/relay/ping   {pubkey, endpoint?}   → heartbeat (registered nodes only)
            // POST /api/relay/send   {from,to?,topic?,body,sig} → store a SIGNED message
            // GET  /api/relay/fetch?to=&topic=&since=      → poll for messages
            if ($sub === 'info' || $sub === '') {
                out(Relay::info());
            }
            if ($sub === 'online') {
                out(['online' => Relay::online()]);
            }
            if ($sub === 'ping') {
                if ($method !== 'POST') { http_response_code(405); out(['error' => 'POST required']); }
                $res = Relay::ping((string) ($body['pubkey'] ?? ''), isset($body['endpoint']) ? (string) $body['endpoint'] : null);
                if (empty($res['ok'])) http_response_code(400);
                out($res);
            }
            if ($sub === 'send') {
                if ($method !== 'POST') { http_response_code(405); out(['error' => 'POST required']); }
                $res = Relay::send($body);
                if (empty($res['ok'])) http_response_code(400);   // signature-gated: reject = 400
                out($res);
            }
            if ($sub === 'fetch') {
                out(Relay::fetch($q));
            }
            http_response_code(404);
            out(['error' => 'unknown relay route']);

        default:
            http_response_code(404);
            out(['error' => 'unknown endpoint']);
    }
} catch (Throwable $e) {
    http_response_code(500);
    error_log('molgang: ' . $e->getMessage());
    out(['error' => 'server error']);   // never leak internals to the client
}
