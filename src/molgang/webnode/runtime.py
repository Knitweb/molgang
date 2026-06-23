"""molgang.webnode — the Python entrypoint that runs the real engine inside a browser tab.

This package is the server-free runtime: instead of a Python ``molgang serve`` process
that browsers poll, the UNCHANGED ``molgang`` + ``knitweb`` engine runs in a Pyodide
module-Worker and IS the peer (Variant A, "the real engine in every tab"). The JS shell
is a thin native carrier (WebRTC plumbing, IndexedDB/OPFS, QR draw/scan, splash); this
package is everything that touches a hashed/signed/economic/ordering path.

Three modules:

  * :mod:`molgang.webnode.contract` — the canonical, versioned JS<->Python ``postMessage``
    RPC + state contract (and a float-rejecting boundary guard).
  * :mod:`molgang.webnode.peer` — :class:`~molgang.webnode.peer.WebPeer`, the in-tab node
    composed from the unchanged identity/ledger/game/faucet/quorum/wire modules plus the
    one new :class:`~molgang.webnode.peer.WebRtcTransport`.
  * this module — :class:`WebNodeRuntime`, the dispatch loop the Worker drives, plus
    :func:`install_worker_bridge`, the glue that wires ``self.onmessage`` / ``postMessage``
    when running under Pyodide.

WHY THE BOUNDARY IS SAFE (sacred invariants, restated for the entrypoint)
-------------------------------------------------------------------------
(a) INTEGER-ONLY — every economic value crossing the boundary is float-checked by
    ``contract.assert_jsonsafe``; the engine math itself is the unchanged integer Python.
(b) NO wall-clock / NO randomness on decision paths — the runtime accepts INJECTED integer
    clocks (``now`` monotonic, ``id_proof_now`` seconds) and CSPRNG nonce bytes from the
    browser (``crypto.getRandomValues``) in the ``hello`` seams and on every tick; it never
    calls ``time.time()`` or ``random`` on a decision path.
(c) BYTE-IDENTITY — frames are produced/parsed only by the shared ``knitweb.p2p.wire``;
    this entrypoint never re-encodes a signed record.

VOCABULARY: Web / Knitweb / Knit / Pulse / Fiber / spiders / PLS. Never "loom".
"""

from __future__ import annotations

import json
import traceback

from . import contract
from .peer import WebPeer, WebRtcTransport
from .contract import CONTRACT_VERSION

__all__ = [
    "CONTRACT_VERSION",
    "WebNodeRuntime",
    "WebPeer",
    "WebRtcTransport",
    "install_worker_bridge",
    "main",
]


class WebNodeRuntime:
    """Owns the single :class:`WebPeer` and turns boundary messages into engine calls.

    Transport-agnostic on purpose: it speaks dicts. The Pyodide bridge
    (:func:`install_worker_bridge`) feeds it ``postMessage`` payloads; a unit test can feed
    it the same dicts with no browser. Every reply / event it emits is a contract-framed,
    float-checked, JSON-safe dict.
    """

    def __init__(self, *, post) -> None:
        """``post(msg: dict)`` delivers one framed message back to the JS shell."""
        self._post = post
        self.peer: WebPeer | None = None

    # -- boot ---------------------------------------------------------------
    def on_hello(self, msg: dict) -> None:
        """Handle the shell's ``hello``: version-gate, derive identity, go ``ready``.

        Fail-closed on contract drift — the postMessage analogue of molgang's
        ``/api/version`` check: if the shell's expected contract version does not match this
        engine, we refuse to run rather than risk a silently divergent surface.
        """
        try:
            want = str(msg.get("contract", ""))
            if want != CONTRACT_VERSION:
                self._post(contract.make_error(
                    None,
                    f"contract mismatch: shell wants {want!r}, engine is {CONTRACT_VERSION!r}",
                    code="contract_mismatch"))
                return
            seed = msg.get("seed")
            if not isinstance(seed, str) or not seed:
                self._post(contract.make_error(None, "hello missing device seed",
                                               code="bad_seed"))
                return
            seams = msg.get("seams") or {}
            self.peer = WebPeer(seed=seed, seams=seams)
            self._post(contract.make_ready(
                contract=CONTRACT_VERSION, identity=self.peer.identity()))
        except Exception as exc:  # noqa: BLE001 — a boot failure is reported, never crashes
            self._post(contract.make_error(None, _fmt(exc), code="boot_failed"))

    # -- per-call dispatch --------------------------------------------------
    async def on_rpc(self, msg: dict) -> None:
        """Validate + execute one RPC, then post the result (or a framed error)."""
        rpc_id = None
        try:
            rpc_id, method, args = contract.parse_rpc(msg)
            if self.peer is None:
                raise RuntimeError("engine not ready — send hello first")
            # Refresh the injected integer seams every call if the shell piggybacks them, so
            # liveness budgets / proof-freshness advance WITHOUT any wall-clock in the engine.
            seams = msg.get("seams") or {}
            if seams:
                self.peer.advance_clock(
                    now=seams.get("now"),
                    id_proof_now=seams.get("id_proof_now"),
                    nonce_hex=seams.get("nonce_hex"))
            payload = await self.peer.call(method, args)
            self._post(contract.make_result(rpc_id, payload))
        except contract.ContractError as exc:
            self._post(contract.make_error(rpc_id, _fmt(exc), code="contract_error"))
        except Exception as exc:  # noqa: BLE001 — every engine error is framed, not fatal
            self._post(contract.make_error(rpc_id, _fmt(exc), code="engine_error"))
        finally:
            self._flush_events()

    def _flush_events(self) -> None:
        """Drain and post any unsolicited engine events (woven items, outbox, sync)."""
        if self.peer is None:
            return
        for ev in self.peer.drain_events():
            self._post(ev)

    # -- the single message entry point the bridge calls --------------------
    async def handle(self, msg: dict) -> None:
        """Route one inbound boundary message by its ``type``."""
        if not isinstance(msg, dict):
            self._post(contract.make_error(None, "boundary message must be a map",
                                           code="bad_message"))
            return
        kind = msg.get("type")
        if kind == contract.MSG_HELLO:
            self.on_hello(msg)
            self._flush_events()
        elif kind == contract.MSG_RPC:
            await self.on_rpc(msg)
        else:
            self._post(contract.make_error(msg.get("id"),
                                           f"unknown message type: {kind!r}",
                                           code="bad_type"))


def _fmt(exc: BaseException) -> str:
    """A compact, side-channel-free error string for the shell (no tracebacks leaked)."""
    return f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__


# ---------------------------------------------------------------------------
# Pyodide bridge — wire self.onmessage / postMessage when running in a Web Worker
# ---------------------------------------------------------------------------

def install_worker_bridge() -> "WebNodeRuntime":
    """Attach a :class:`WebNodeRuntime` to the Pyodide module-Worker's message channel.

    Expects to run INSIDE a module-type Web Worker under Pyodide (``import js`` exposes the
    Worker global scope ``self`` with ``postMessage`` and ``onmessage``). The JS shell does:

        const worker = new Worker("worker.js", {type: "module"});   // classic importScripts is out
        // worker.js loads Pyodide, micropips the engine wheel, then runs:
        //   import molgang.webnode as wn; wn.install_worker_bridge()
        worker.postMessage({type:"hello", contract:"webnode/1", seed:<idb seed>, seams:{...}});

    Each inbound ``MessageEvent.data`` is handled by the runtime; replies/events go back via
    ``self.postMessage``. Because the engine is async, each message is scheduled on the
    Pyodide event loop. Returns the runtime so a caller can also drive it directly.
    """
    import js                       # provided by Pyodide inside the Worker
    import pyodide.ffi              # to_js / create_proxy
    import asyncio

    def _post(msg: dict) -> None:
        # Convert the Python dict to a structured-clone-safe JS object. dict_converter
        # produces a plain JS Object (not a Map) so the shell reads ``msg.type`` etc.
        js.self.postMessage(
            pyodide.ffi.to_js(msg, dict_converter=js.Object.fromEntries))

    runtime = WebNodeRuntime(post=_post)

    def _on_message(event) -> None:
        # event.data is the JS payload the shell posted; .to_py() makes a Python dict.
        try:
            data = event.data.to_py()
        except Exception:  # noqa: BLE001 — a non-convertible payload is reported, not fatal
            _post(contract.make_error(None, "undecodable boundary payload",
                                      code="bad_payload"))
            return
        # Schedule async handling on the Pyodide loop; never block the Worker thread.
        asyncio.ensure_future(runtime.handle(data))

    # Keep the proxy alive for the Worker's lifetime (Pyodide requires an explicit proxy
    # for a JS event callback into Python).
    js.self.onmessage = pyodide.ffi.create_proxy(_on_message)
    # Tell the shell the engine module is loaded and the bridge is live (pre-hello). The
    # shell waits for this before posting ``hello`` so it never races the import.
    _post({"type": "loaded", "contract": CONTRACT_VERSION})
    return runtime


def main() -> None:
    """A tiny stdout REPL harness for running the engine OUTSIDE the browser (CI/dev).

    Reads one JSON boundary message per line from stdin and writes each framed reply as a
    JSON line to stdout. This lets the L6 conformance corpus and parity tests drive the
    exact same dispatch the Worker uses — proving server-mode and tab-mode agree on every
    ``state_root`` — without a browser. Not used in production (the Worker is).
    """
    import asyncio
    import sys

    out = []

    def _post(msg: dict) -> None:
        out.append(msg)

    runtime = WebNodeRuntime(post=_post)

    async def _run() -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                _post(contract.make_error(None, "invalid JSON line", code="bad_json"))
            else:
                await runtime.handle(msg)
            while out:
                sys.stdout.write(json.dumps(out.pop(0)) + "\n")
            sys.stdout.flush()

    asyncio.run(_run())


if __name__ == "__main__":  # pragma: no cover - dev harness only
    main()
