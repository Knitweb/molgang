<?php
// Copy this to php/config.php on the host and fill in the real MySQL credentials.
// config.php is gitignored and is NEVER committed (and is blocked from HTTP by .htaccess).
return [
    'host' => 'localhost',          // TransIP shared hosting: usually 'localhost'
    'name' => 'YOUR_DB_NAME',       // e.g. 5martm_ED
    'user' => 'YOUR_DB_USER',       // e.g. 5martm_develuse
    'pass' => 'YOUR_DB_PASSWORD',   // set on the host only — keep out of git
];
