# Wallet recovery — restore your MOLGANG identity (#141)

MOLGANG wallets are **non-custodial and device-derived**: there is no server, no
account database, and no custodial reset. That means a phone wipe would lose your
identity — unless you keep your **recovery phrase**.

## What the recovery phrase is

A recovery phrase is a **33-word backup of your wallet's private key** (32 key
bytes + 1 checksum word). The phrase *is* the key — anyone who has it controls
the wallet — so treat it like a password:

- Write it down offline; never paste it into a website or share it.
- It never leaves your device: `molgang.recovery.seed_to_phrase` runs in your tab
  (the `recovery_phrase` RPC), the same code path a test verifies is byte-exact.

## Restore on a new device

1. Open MOLGANG on the new device.
2. Choose **Restore wallet** and type your 33-word phrase.
3. `phrase_to_seed` decodes it back to your private key (checksum-verified — a
   mistyped word is rejected with a clear error), and the wallet is rebuilt.
4. Because the **address is fully determined by the key**, your balance
   (re-derived from the knitweb account braid) and your reputation (derived from
   your address's woven Fibers) come back intact. Nothing was stored on a server;
   the key alone restores everything.

## Non-custodial guarantees

- **No custodial reset.** There is no "forgot phrase" support path — losing the
  phrase means losing the wallet, exactly like a self-custody crypto wallet. This
  is a deliberate trade for having no server that could be breached or subpoenaed.
- **Optional social re-bind** (future): peers who have vouched for you can
  attest a *new* key to your reputation, without any central escrow of the old
  key. This is additive; it never weakens the non-custodial default.

## Try it (engine)

```python
from molgang.recovery import seed_to_phrase, phrase_to_seed
phrase = seed_to_phrase(my_wallet_priv_hex)   # 33 words
assert phrase_to_seed(phrase) == my_wallet_priv_hex
```
