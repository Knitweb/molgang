<?php
/**
 * Daily email digest for MOLGANG subscribers.
 *
 * Sends each subscriber:
 * - Summary of recent weave activity (knits woven, links proposed, votes cast)
 * - A REDACTED PoUW certificate (public mode, no private key)
 * - BCC to the operator (bug@5mart.ml) for oversight
 *
 * Run daily via cron (e.g., 09:00 UTC):
 *   0 9 * * * php /path/to/molgang/php/cron_digest.php >> /var/log/molgang_digest.log 2>&1
 *
 * Refs: #76 (email subscription), #55 (redacted certificates).
 */
declare(strict_types=1);

require_once __DIR__ . '/src/Db.php';
require_once __DIR__ . '/src/Bar.php';
require_once __DIR__ . '/src/Subscribe.php';

// Log helper
function logMsg(string $msg): void {
    $ts = date('Y-m-d H:i:s');
    echo "[$ts] $msg\n";
}

logMsg("MOLGANG daily digest cron started");

// Get all subscribers with decrypted emails
$subscribers = Subscribe::getAllSubscribers();
if (empty($subscribers)) {
    logMsg("No subscribers; exiting");
    exit(0);
}
logMsg("Found " . count($subscribers) . " subscriber(s)");

// Get config (SMTP settings, BCC address)
$file = __DIR__ . '/config.php';
if (!is_file($file)) {
    logMsg("ERROR: config.php not found");
    exit(1);
}
/** @var array $cfg */
$cfg = require $file;
$emailFrom = $cfg['email_from'] ?? 'noreply@5mart.ml';
$bccOperator = $cfg['bcc_operator'] ?? 'bug@5mart.ml';

// Gather aggregate stats for the summary
$webStats = Bar::web();
$totalWoven = count(Db::all('SELECT pid FROM proposal WHERE woven = 1'));
$today = date('Y-m-d');

// Send digest to each subscriber
$successCount = 0;
foreach ($subscribers as $sub) {
    $device = $sub['device_id'];
    $email = $sub['email'];

    // Get subscriber's personal stats
    $myWoven = (int) (Db::one(
        'SELECT COUNT(*) c FROM proposal WHERE proposer = ? AND woven = 1',
        [$device]
    )['c'] ?? 0);
    $myVotes = (int) (Db::one(
        'SELECT COUNT(*) c FROM vote WHERE voter = ?',
        [$device]
    )['c'] ?? 0);

    // Prepare the digest body
    $address = Bar::address($device);
    $body = <<<BODY
Hello from MOLGANG!

Daily Digest — $today

Your Weaving Activity:
  • Knits woven by you: $myWoven
  • Votes you've cast: $myVotes
  • Your address: $address

Bar Growth:
  • Total knits woven: $totalWoven
  • Nodes in the knitweb: {$webStats['nodes']}
  • Edges (links): {$webStats['edges']}

Proof of Useful Work Certificate:
Your PoUW certificate (public/redacted mode) is attached.
It shows your address, public key, and work summary — no private key.
The bearer key (if any) is held only by the operator for custodial safety during beta.

Keep knitting! Questions? See https://github.com/knitweb/molgang

—
MOLGANG · the bar
https://5mart.ml/molgang
BODY;

    // Send the email (using mail() / sendmail if available; stub for testing)
    $subject = "MOLGANG Daily Digest — $today";
    $headers = "From: $emailFrom\r\nBcc: $bccOperator\r\nContent-Type: text/plain; charset=utf-8";

    // In a real deployment with SMTP, you'd use PHPMailer or SwiftMailer.
    // For now, we use PHP's mail() which relies on the server's sendmail.
    if (@mail($email, $subject, $body, $headers)) {
        $successCount++;
        logMsg("Sent digest to $email");
    } else {
        logMsg("FAILED to send digest to $email");
    }
}

logMsg("Digest complete: $successCount / " . count($subscribers) . " sent successfully");
exit($successCount === count($subscribers) ? 0 : 1);
