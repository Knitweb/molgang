<?php
// MOLGANG dapp — front controller. Serves the JSON API; Apache serves the static SPA
// (index.html / app.js / style.css / avatars) directly via .htaccess. Request-driven:
// every call is a fresh PHP process, so it runs on plain shared hosting (no daemon).
declare(strict_types=1);

require_once __DIR__ . '/../src/Bar.php';

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

// route = the path segment after "/api/" (works under any base, e.g. /molgang/)
$uri = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?? '/';
$route = preg_match('~/api/([a-z\-]+)~', $uri, $m) ? $m[1] : '';
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

        default:
            http_response_code(404);
            out(['error' => 'unknown endpoint']);
    }
} catch (Throwable $e) {
    http_response_code(500);
    error_log('molgang: ' . $e->getMessage());
    out(['error' => 'server error']);   // never leak internals to the client
}
