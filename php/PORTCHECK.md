# Port-openness findings — 5mart.ml shared hosting (Refs #62)

**Question:** can 5mart.ml act as a raw-TCP p2p peer (bind a public listener), or must the
knitweb transport be an HTTP relay through PHP?

**Conclusion: raw inbound p2p is NOT possible. The transport must be an HTTP relay through
PHP behind the always-on nginx.** This is what `php/src/Relay.php` implements (Refs #61).

## Host facts
- TransIP shared hosting, `tb-nl01-linssh057`, Linux 6.1, **PHP 8.1.34** at `/usr/local/bin/php`.
- No `python3`, no `nc`/`netcat`, no `ss`/`netstat` on the shell `PATH`.
- DB `5martm_ED` (MySQL) is reachable **only from the web/PHP-FPM context**, not the SSH shell
  (a CLI connect to `127.0.0.1` is refused; the same `Db` config works fine over HTTPS). The
  schema was therefore applied via a one-shot, token-gated web migration, then deleted.

## Inbound TCP (can a process accept connections from the internet?) — NO
A PHP process **can** `stream_socket_server()` bind locally on high ports (8787, 18080, 39000,
49152, 51820 all bound; loopback bind also succeeds), and `disable_functions` is empty
(`exec`, `proc_open`, `pcntl_fork`, `fsockopen` all available). **But binding ≠ reachable.**

Definitive external-reachability test: a listener was bound to `0.0.0.0:39271` on the host, then
connected to from a separate machine over the public internet:

| target | result |
|---|---|
| `80.69.66.28:39271` (host's outbound IP) | **connection timed out (filtered)** |
| `85.10.159.225:39271` (the IP `5mart.ml` resolves to) | **timed out / unreachable** |
| host-side listener | **received NO inbound connection** |

The connection is *filtered* (silent drop), not *refused* — a perimeter firewall blocks all
inbound TCP from the internet. Note `5mart.ml` (85.10.159.225, the web front-end / reverse
proxy) is a **different IP** from the host's egress (80.69.66.28), confirming a NAT/proxy
perimeter in front of the shared host. **A listening peer here is unreachable from the internet.**

## Outbound TCP (can the host reach other peers?) — YES
All outbound connects succeeded from the host:

| target | result |
|---|---|
| `1.1.1.1:443` (https) | CONNECTED |
| `1.1.1.1:80` (http)  | CONNECTED |
| `8.8.8.8:53` (dns)   | CONNECTED |
| `github.com:443`     | CONNECTED |

## Implication for the knitweb transport
- Inbound listeners are dead on arrival → **no raw libp2p/QUIC/TCP peer**.
- The only always-reachable, always-on transport is **nginx → PHP over HTTPS**.
- So peers rendezvous **request-driven**: a node POSTs a signed message to 5mart.ml, the relay
  stores it in MySQL, and the recipient GETs it later. Outbound being open means the node can
  also *push* to other relays if needed. This is exactly `php/src/Relay.php` + the `/api/relay/*`
  and `/api/onboard/*` endpoints.
