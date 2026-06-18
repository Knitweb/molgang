"""On-chain-style provenance — anchor MOLGANG's confirmed chemistry to OriginTrail.

The set of peer-confirmed (woven) bonds is the game's knowledge web. We weave it into a
knitweb fabric `Web`, beat a `Pulse`, checkpoint it, and anchor the checkpoint root to
**OriginTrail** as a Knowledge Asset — yielding a Universal Asset Locator (**UAL**) plus a
notary-signed `AnchorReceipt` anyone can verify offline. So the game's chemistry knowledge
becomes independently auditable on a Decentralised Knowledge Graph: real web3 provenance, not
a badge. (Swap the in-process OriginTrail backend for a live DKG client and the UAL contract
is unchanged.)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from knitweb.anchor import Notary, verify_receipt
from knitweb.anchor.origintrail import OriginTrailAnchorBackend
from knitweb.core import crypto
from knitweb.core.pulse import Pulse
from knitweb.fabric.items import checkpoint, web_state_root
from knitweb.fabric.web import Web


@dataclass(frozen=True)
class Anchor:
    """A verifiable provenance anchor for the confirmed-chemistry web."""

    ual: str            # OriginTrail Universal Asset Locator for this state
    state_root: str     # the fabric checkpoint root the UAL commits to
    epoch: int
    bonds: int          # how many confirmed bonds are committed
    receipt_cid: str    # CID of the notary-signed AnchorReceipt
    verified: bool      # receipt signature valid AND the UAL resolves on OriginTrail


def anchor_chemistry(bonds: Iterable[dict], *, notary_priv: str | None = None,
                     timestamp: int = 1) -> Anchor:
    """Anchor the confirmed bonds (``{formula,name,confirmations,by,...}``) to OriginTrail."""
    bonds = list(bonds)
    web = Web()
    for b in sorted(bonds, key=lambda x: x["formula"]):
        web.weave({
            "molecule": b["formula"],
            "name": b.get("name", ""),
            "confirmations": int(b.get("confirmations", 0)),
            "by": b.get("by", ""),
        })

    pulse = Pulse(interval_s=60, genesis_ts=0)
    beat = pulse.beat(timestamp=timestamp, state_root=web_state_root(web))
    cp = checkpoint(web, beat)

    backend = OriginTrailAnchorBackend()
    notary = Notary(notary_priv or crypto.generate_keypair()[0])
    receipt = notary.anchor(cp, backend, timestamp)
    verified = verify_receipt(receipt, cp) and backend.resolve(receipt.external_ref) is not None

    return Anchor(
        ual=receipt.external_ref, state_root=cp.state_root, epoch=cp.epoch,
        bonds=len(bonds), receipt_cid=receipt.cid, verified=verified,
    )
