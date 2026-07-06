"""#141 — non-custodial wallet recovery phrase restores the identical identity."""
import pytest

from molgang.bar import Bar
from molgang.recovery import RecoveryError, phrase_to_seed, seed_to_phrase


def test_phrase_round_trips_a_seed_byte_exact():
    seed = "ab" * 32
    assert phrase_to_seed(seed_to_phrase(seed)) == seed
    # 33 words, deterministic
    assert len(seed_to_phrase(seed).split()) == 33
    assert seed_to_phrase(seed) == seed_to_phrase(seed)


def test_arbitrary_device_seed_gets_a_stable_phrase():
    ph = seed_to_phrase("device-uuid-xyz")
    # decoding then re-encoding is stable (the phrase pins a concrete 32-byte seed)
    assert seed_to_phrase(phrase_to_seed(ph)) == ph


def test_bad_checksum_and_wrong_length_are_rejected():
    ph = seed_to_phrase("cd" * 32).split()
    ph[0] = "bab" if ph[0] != "bab" else "bak"          # corrupt one word
    with pytest.raises(RecoveryError):
        phrase_to_seed(" ".join(ph))
    with pytest.raises(RecoveryError):
        phrase_to_seed("pit pit pit")                    # too short
    with pytest.raises(RecoveryError):
        phrase_to_seed(" ".join(["zzz"] * 33))           # unknown word


def test_restore_gives_the_same_wallet_address_non_custodial():
    # the phrase encodes the wallet's PRIVATE KEY; restoring it rebuilds the exact
    # same account (address), so balances (from the braid) + reputation follow it.
    from knitweb.core import crypto
    from knitweb.ledger.node import AccountNode

    wallet = AccountNode.from_seed("some-device-id")
    addr, priv = wallet.address, wallet.priv

    phrase = seed_to_phrase(priv)                         # backup the key, not the device id
    restored_priv = phrase_to_seed(phrase)
    assert restored_priv == priv                         # byte-exact key recovery

    # a fresh instance rebuilds the identical wallet from the recovered key alone
    restored = AccountNode(priv=restored_priv, pub=crypto.public_from_private(restored_priv))
    assert restored.address == addr                      # same identity, non-custodial


def test_canonical_hex_device_seed_round_trips_into_the_same_bar_wallet():
    # when the device seed is the canonical 64-hex form, the phrase round-trips it
    # verbatim, so even the device-seed path restores the same Bar wallet
    seed = "ab" * 32
    bar1 = Bar(world_path=None)
    a = bar1.join("Ada", table_id="periodic", device=seed)
    bar2 = Bar(world_path=None)
    b = bar2.join("Ada", table_id="periodic", device=phrase_to_seed(seed_to_phrase(seed)))
    assert b.player.address == a.player.address


def test_webnode_exposes_the_recovery_phrase_rpc():
    import asyncio
    from molgang.webnode.contract import make_hello
    from molgang.webnode.runtime import WebNodeRuntime

    out = []
    rt = WebNodeRuntime(post=out.append)
    rt.on_hello(make_hello(seed="dev-seed", seams={"now": 1, "id_proof_now": 1, "nonce_hex": "00" * 16}))

    async def go():
        await rt.handle({"type": "rpc", "id": 1, "method": "recovery_phrase", "args": {},
                         "seams": {"now": 2, "id_proof_now": 2, "nonce_hex": "01" * 16}})
    asyncio.run(go())
    res = [m for m in out if m.get("id") == 1][-1]
    assert res["type"] == "result" and len(res["payload"]["phrase"].split()) == 33
    # the phrase decodes to the wallet's private key (64-hex), non-custodial backup
    priv = phrase_to_seed(res["payload"]["phrase"])
    assert len(priv) == 64
