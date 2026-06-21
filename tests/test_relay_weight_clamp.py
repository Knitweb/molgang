"""Security regression: a relayed item's confirmations/validators are self-reported by the untrusted
sender. A forged confirmations=9999 used to weave/bump the edge at a dominating weight (a peer wove
"Gold is Lead" at 9999). The relay now clamps both on ingest to RELAY_MAX_CONFIRMATIONS."""

from __future__ import annotations

from molgang.relay_sync import clamp_relayed_weights, RELAY_MAX_CONFIRMATIONS
from molgang.world import WovenItem


def _item(confirmations, validators=0, kind="link"):
    return WovenItem(kind=kind, by="peer:evil", fiber_cid="cid", confirmations=confirmations,
                     subject="Gold", object="Lead", relation="is", validators=validators)


def test_forged_high_confirmations_is_clamped():
    it = clamp_relayed_weights(_item(9999))
    assert it.confirmations == RELAY_MAX_CONFIRMATIONS


def test_forged_high_validators_cannot_widen_the_cap():
    it = clamp_relayed_weights(_item(9999, validators=9999))
    assert it.validators == RELAY_MAX_CONFIRMATIONS
    assert it.confirmations == RELAY_MAX_CONFIRMATIONS


def test_small_validators_tighten_the_cap():
    it = clamp_relayed_weights(_item(50, validators=3))
    assert it.confirmations == 3  # capped at the (clamped) claimed validator count


def test_honest_small_weight_is_preserved():
    it = clamp_relayed_weights(_item(5, validators=8))
    assert it.confirmations == 5
    assert it.validators == 8


def test_nonpositive_and_nonint_floor_to_one():
    assert clamp_relayed_weights(_item(0)).confirmations == 1
    assert clamp_relayed_weights(_item(-7)).confirmations == 1
    assert clamp_relayed_weights(_item("9999")).confirmations == 1  # type: ignore[arg-type]
