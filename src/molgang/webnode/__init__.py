"""molgang.webnode — the in-tab, server-free peer bridge (Pyodide engine worker side).

Server-free architecture: every browser tab runs the unchanged molgang + knitweb Python via
Pyodide; this subpackage is the thin bridge the JS shell drives over postMessage RPC. It hosts
the deterministic union-of-co-woven-fibers merge so two peers converge to the same
web_state_root / UAL with no server, preserving every sacred invariant (integer-only, no
wall-clock/randomness on decision paths, byte-identity).

Submodules:
  * :mod:`molgang.webnode.contract`     — versioned JS<->Python postMessage RPC + state contract.
  * :mod:`molgang.webnode.merge_bridge` — integer-deterministic co-woven-fiber merge.
  * :mod:`molgang.webnode.onboard_verify` — signature-gated QR onboarding (verify-before-connect).
  * :mod:`molgang.webnode.peer`         — WebPeer + the one new WebRtcTransport.
  * :mod:`molgang.webnode.runtime`      — WebNodeRuntime dispatch loop + install_worker_bridge glue.

VOCABULARY: Web / Knitweb / Knit / Pulse / Fiber / spiders / PLS. (Never "loom".)
"""

# Light, dependency-free symbols are safe to re-export eagerly.
from .merge_bridge import MergeBridge, account_from_seed, WEB_TOPIC

# Heavier entrypoints (peer.py / runtime.py pull in the full knitweb engine) are re-exported
# lazily via PEP 562 so a bare `import molgang.webnode` does not force the engine to load
# outside Pyodide. `from molgang.webnode import WebNodeRuntime` still works.
_LAZY = {
    "WebNodeRuntime": ".runtime",
    "install_worker_bridge": ".runtime",
    "WebPeer": ".peer",
    "WebRtcTransport": ".peer",
}

__all__ = ["MergeBridge", "account_from_seed", "WEB_TOPIC", *_LAZY.keys()]


def __getattr__(name):
    mod = _LAZY.get(name)
    if mod is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib
    return getattr(importlib.import_module(mod, __name__), name)


def __dir__():
    return sorted(__all__)
