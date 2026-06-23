"""The canonical JS <-> Python message + state contract for the MOLGANG webnode.

The browser shell (JS, main thread) and the engine (this Python, running unchanged
inside a Pyodide module-Worker) communicate ONLY through ``postMessage`` RPC. This
module is the single, versioned source of truth for the shape of every message that
crosses that boundary, so the two sides can never silently disagree.

THE BOUNDARY IS NOT A TRUST OR HASH BOUNDARY
--------------------------------------------
Nothing here re-implements an economic, scoring, ordering, or encoding rule. The JS
shell NEVER does faucet math, canonical CBOR, CIDv1, signing, or quorum tallying —
those live exclusively in the unchanged ``molgang`` + ``knitweb`` Python bytes that
this same Worker runs (see :mod:`molgang.webnode.peer`). A request is a plain method
name + JSON-safe args; a reply is a plain JSON-safe snapshot. By construction no JS
value ever reaches a hashed/signed/economic path, so sacred invariant (c) byte-identity
is preserved across the WASM boundary: a Knit's CID and a relay signature are produced
by the identical ``.py`` on every peer.

SACRED INVARIANTS this module upholds
-------------------------------------
(a) INTEGER-ONLY: every economic field that crosses the boundary is an ``int`` (PLS or
    integer micro-PLS, 1 PLS = 1_000_000 micro-PLS). :func:`assert_jsonsafe` REJECTS
    ``float`` exactly as :mod:`knitweb.core.canonical` does, so a stray JS number can
    never smuggle a float onto an economic/scoring path even in a display snapshot.
(b) NO wall-clock / NO randomness on decision paths: the only time/seed values that
    cross are explicitly-tagged *injected* integer seams (an integer monotonic clock
    for liveness budgets, an integer ``id_proof`` seconds clock for identity-proof
    freshness, and CSPRNG nonce *bytes* sourced from the browser ``crypto.getRandomValues``
    — never ``Math.random``). They are carried as ints/hex, never used to order or hash.
(c) BYTE-IDENTITY: the wire/crypto/canonical encoders are NOT here; they are the shared
    Python. This file only frames the local RPC, which never touches wire bytes.

VOCABULARY: Web / Knitweb / Knit / Pulse / Fiber / spiders / PLS. Never "loom".
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "CONTRACT_VERSION",
    "PROTOCOL_NAME",
    "RELAY_PREIMAGE_TAG",
    "WEB_TOPIC",
    "MAX_FRAME_BYTES",
    "MICROPULSES_PER_PULSE",
    "MSG_HELLO",
    "MSG_READY",
    "MSG_RPC",
    "MSG_RESULT",
    "MSG_ERROR",
    "MSG_EVENT",
    "RPC_METHODS",
    "EVENT_KINDS",
    "ContractError",
    "make_hello",
    "make_ready",
    "make_result",
    "make_error",
    "make_event",
    "parse_rpc",
    "assert_jsonsafe",
]

# ---------------------------------------------------------------------------
# Versioning + frozen protocol constants (mirrored, never re-derived, in JS)
# ---------------------------------------------------------------------------

#: Bump on ANY breaking change to the RPC surface, an event shape, or a frozen
#: constant below. The JS shell sends its expected version in ``hello``; the engine
#: refuses to run against a mismatched shell (a fail-closed contract-drift gate, the
#: postMessage analogue of molgang's ``/api/version`` check). It is also the version
#: stamped on the published golden-vector conformance corpus (L6) so a Rust/TS peer
#: can target the exact same contract.
CONTRACT_VERSION = "webnode/1"

PROTOCOL_NAME = "molgang-webnode"

# -- Constants that MUST byte-match the shared engine / live relay (do NOT fork) ----
# These are duplicated here ONLY as read-only assertions the shell can display and the
# conformance suite can pin; the engine imports the real values from the unchanged
# Python so there is exactly one runtime source.

#: The exact relay signed pre-image tag. The full pre-image a sender signs is
#: ``"knitweb-relay:v1\n{to}\n{topic}\n{body}"`` (``to=""`` for a broadcast) — see
#: ``molgang.relay_sync.signed_preimage``. Reproduced here for the conformance corpus.
RELAY_PREIMAGE_TAG = "knitweb-relay:v1"

#: Canonical relay topic the shared web rides on (``molgang.relay_sync.WEB_TOPIC``).
WEB_TOPIC = "knitweb.web"

#: Hard per-frame ceiling, IDENTICAL to ``knitweb.p2p.wire.MAX_FRAME_BYTES`` (8 MiB).
#: Liveness-coupled to ``inventory.SERVE_BYTES_PER_WINDOW``; never lower it.
MAX_FRAME_BYTES = 8 * 1024 * 1024  # 8388608

#: 1 PLS = 1_000_000 micro-PLS (``molgang.game.MICROPULSES_PER_PULSE``).
MICROPULSES_PER_PULSE = 1_000_000

# ---------------------------------------------------------------------------
# Message types crossing the worker boundary
# ---------------------------------------------------------------------------

MSG_HELLO = "hello"      # shell -> worker: announce expected contract version + seams
MSG_READY = "ready"      # worker -> shell: engine booted, identity derived, contract OK
MSG_RPC = "rpc"          # shell -> worker: invoke one engine method
MSG_RESULT = "result"    # worker -> shell: a successful RPC reply (carries the rpc id)
MSG_ERROR = "error"      # worker -> shell: a failed RPC / boot (carries the rpc id if any)
MSG_EVENT = "event"      # worker -> shell: an unsolicited push (woven item, peer up/down)


class ContractError(ValueError):
    """Raised when a boundary message violates this contract (bad type, float, ...)."""


# ---------------------------------------------------------------------------
# The RPC surface — replaces every molgang ``/api/*`` HTTP route with an in-worker call
# ---------------------------------------------------------------------------
#
# Each entry maps the public method name (what the shell sends as ``method``) to the
# tuple of accepted argument keys. These are the SAME operations the server-mode Bar
# exposed (``join/sit/propose/vote/spiral/certificate/state``) — now direct in-worker
# Bar method calls with no HTTP, no polling, no server singleton. The engine validates
# args against these tuples so a typo'd field fails closed instead of silently no-op'ing.

RPC_METHODS: dict[str, tuple[str, ...]] = {
    # --- identity / lifecycle ---
    "version": (),                                   # {contract, engine, molgang, knitweb}
    "identity": (),                                  # derive/return this tab's account (pubkey/address)
    # --- bar gameplay (one-to-one with the retired POST routes) ---
    "state": ("sid",),                               # full bar snapshot (was GET /api/state)
    "join": ("name", "avatar", "table", "device", "today"),   # was POST /api/join
    "sit": ("sid", "table"),                         # was POST /api/sit
    "stand": ("sid",),
    "leave": ("sid",),
    "heartbeat": ("sid",),
    "rename_table": ("sid", "table", "name"),
    "propose": ("sid", "term", "topic"),             # was POST /api/propose (spends silk)
    "vote": ("sid", "pid", "verdict"),               # was POST /api/vote (stakes a pulse)
    "spiral_propose": ("sid", "lines"),              # was POST /api/spiral/propose
    "spiral_vote": ("sid", "cid", "verdict"),        # was POST /api/spiral/vote
    "certificate": ("sid", "mode"),                  # PoUW certificate payload
    "web": (),                                       # woven-web view
    "graph": ("limit",),
    "leaderboard": (),
    # --- serverless p2p control (driven by the shell, executed by the engine) ---
    "peer_start": ("seed_peer",),                    # boot the BaseNode + WebRtcTransport
    "peer_stop": (),
    "ingest_frame": ("frame_b64", "peer_key"),       # a DataChannel onmessage delivered an opaque frame
    "drain_outbox": (),                              # pull queued opaque frames the shell must send
    "qr_offer": (),                                  # mint a wallet-signed onboarding QR payload
    "qr_admit": ("offer",),                          # verify-before-connect a scanned QR; returns ok/peer
    "relay_pull": ("base",),                         # optional opaque-mailbox first-contact drain
}

# ---------------------------------------------------------------------------
# Unsolicited event kinds the engine pushes to the shell
# ---------------------------------------------------------------------------

EVENT_KINDS = frozenset({
    "woven",        # a new WovenItem was woven locally (mirrors World.on_weave) -> redraw web
    "peer_up",      # a DataChannel to a verified peer opened
    "peer_down",    # a peer disconnected
    "outbox",       # there are opaque frames queued for the shell to send over WebRTC
    "synced",       # a pull/anti-entropy round converged; carries the new state_root
    "faucet",       # the device faucet was opened/restored (display µPLS + PLS)
})


# ---------------------------------------------------------------------------
# JSON-safety / float-rejection (sacred invariant a, mirrored from canonical.py)
# ---------------------------------------------------------------------------

def assert_jsonsafe(value: Any, *, _depth: int = 0) -> Any:
    """Return a JSON-safe, FRACTIONAL-FLOAT-FREE copy of ``value``.

    Mirrors the float rejection in :mod:`knitweb.core.canonical` on every path that
    could be mistaken for money/state/score: a *fractional* ``float`` (anything not
    exactly an integer) is refused outright — money/state/scores are integers (PLS or
    micro-PLS), never a fractional float. ``bool`` is preserved as a genuine boolean,
    never coerced to an int.

    A *whole-number* float (e.g. ``100.0``) is COERCED to ``int`` rather than rejected.
    The only floats the engine ever emits across this boundary are display-only session
    timestamps stamped from the INJECTED **integer** monotonic clock (the Bar's type hint
    wraps that integer in ``float()`` — ``WebPeer._injected_clock``), so they are always
    integral and never reach a hashed/CID/ordering path. Coercing them keeps the snapshot
    integer-only on the wire while a genuine fractional ``1.5`` (which could only come from
    a real float on an economic path) is still refused — so the guard stays strict where it
    matters. Bounded depth so a hostile nested structure cannot exhaust the engine's stack.
    """
    if _depth > 64:
        raise ContractError("boundary value nests too deep")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, float):
        # Reject any value with a fractional part; coerce a whole number to int. This is
        # the ONLY place a float may cross, and only as an integral display timestamp.
        if value != value or value in (float("inf"), float("-inf")):
            raise ContractError("non-finite floats are forbidden across the boundary")
        as_int = int(value)
        if as_int != value:
            raise ContractError(
                "fractional floats are forbidden across the JS<->Python boundary; "
                "use integer (micro-)PLS"
            )
        return as_int
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return [assert_jsonsafe(item, _depth=_depth + 1) for item in value]
    if isinstance(value, dict):
        out: dict = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise ContractError("boundary map keys must be strings (JSON objects)")
            out[k] = assert_jsonsafe(v, _depth=_depth + 1)
        return out
    raise ContractError(f"value of type {type(value).__name__} is not JSON-safe")


# ---------------------------------------------------------------------------
# Constructors / parsers (used by the worker; the JS shell mirrors these shapes)
# ---------------------------------------------------------------------------

def make_hello(*, contract: str = CONTRACT_VERSION, seed: str,
               seams: dict | None = None) -> dict:
    """Shell -> worker boot message.

    ``seed`` is the device seed (from IndexedDB / the QR) the engine feeds into
    ``AccountNode.from_seed`` — this is the SAME key that signs the onboarding QR
    challenge, and replaces the retired ``pulse_host.py`` subprocess identity. ``seams``
    carries the INJECTED integer clocks/nonce policy (never wall-clock/Math.random):
    ``{"now": <int monotonic>, "id_proof_now": <int seconds>, "nonce_hex": <csprng hex>}``.
    """
    return {
        "type": MSG_HELLO,
        "contract": contract,
        "seed": seed,
        "seams": assert_jsonsafe(dict(seams or {})),
    }


def make_ready(*, contract: str, identity: dict) -> dict:
    """Worker -> shell: engine booted and the contract version matched."""
    return {"type": MSG_READY, "contract": contract,
            "identity": assert_jsonsafe(identity)}


def make_result(rpc_id: int, payload: Any) -> dict:
    """Worker -> shell: a successful RPC reply correlated by ``rpc_id``."""
    if not isinstance(rpc_id, int) or isinstance(rpc_id, bool):
        raise ContractError("rpc_id must be an integer")
    return {"type": MSG_RESULT, "id": rpc_id, "ok": True,
            "payload": assert_jsonsafe(payload)}


def make_error(rpc_id: int | None, message: str, *, code: str = "error") -> dict:
    """Worker -> shell: a failed RPC or boot. ``rpc_id`` is None for a boot failure."""
    if rpc_id is not None and (not isinstance(rpc_id, int) or isinstance(rpc_id, bool)):
        raise ContractError("rpc_id must be an integer or None")
    return {"type": MSG_ERROR, "id": rpc_id, "ok": False,
            "code": str(code), "error": str(message)}


def make_event(kind: str, payload: Any) -> dict:
    """Worker -> shell: an unsolicited push (one of :data:`EVENT_KINDS`)."""
    if kind not in EVENT_KINDS:
        raise ContractError(f"unknown event kind: {kind!r}")
    return {"type": MSG_EVENT, "kind": kind, "payload": assert_jsonsafe(payload)}


def parse_rpc(msg: dict) -> tuple[int, str, dict]:
    """Validate a shell -> worker RPC and return ``(rpc_id, method, args)``.

    Enforces: a known method, an integer correlation id, and ONLY the argument keys
    declared in :data:`RPC_METHODS` for that method — an unknown field fails closed
    rather than being silently ignored. Args are float-checked via :func:`assert_jsonsafe`.
    """
    if not isinstance(msg, dict) or msg.get("type") != MSG_RPC:
        raise ContractError("not an rpc message")
    rpc_id = msg.get("id")
    if not isinstance(rpc_id, int) or isinstance(rpc_id, bool):
        raise ContractError("rpc id must be an integer")
    method = msg.get("method")
    if method not in RPC_METHODS:
        raise ContractError(f"unknown rpc method: {method!r}")
    raw_args = msg.get("args") or {}
    if not isinstance(raw_args, dict):
        raise ContractError("rpc args must be a map")
    allowed = RPC_METHODS[method]
    args: dict = {}
    for k, v in raw_args.items():
        if k not in allowed:
            raise ContractError(f"method {method!r} does not accept arg {k!r}")
        args[k] = assert_jsonsafe(v)
    return rpc_id, method, args
