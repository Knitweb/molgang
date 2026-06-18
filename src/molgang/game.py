"""MOLGANG game engine — chemistry on the Knitweb.

The mapping (this is the whole point — the game *is* the protocol):

| Chemistry / game            | Knitweb primitive                                   |
|-----------------------------|-----------------------------------------------------|
| Forming a **bond**          | a **Knit** (a two-party transfer over the ledger)   |
| A molecule's growing chain  | a **Fiber** (the immutable account-state commitment)|
| Peers **voting** on a bond  | **PLS (pulses)** staked + a `pouw.quorum` verdict   |
| The bond is accepted        | a **confirm quorum** → woven into the player's Braid|
| Free starter material       | **silk** (thread) + **pulses** from the faucet      |

Every vote is a *real* Knit settled on a *real* knitweb account, so playing the game
literally weaves the player's first Knits and Fibers. Validation uses the real
`knitweb.pouw.quorum` BFT tally — no game-only shortcut.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from knitweb.ledger.node import AccountNode
from knitweb.pouw import quorum

from . import chemistry
from .chemistry import Bond

FAUCET_PULSES = 50      # free PLS every new player gets to start voting/playing
FAUCET_SILK = 10        # free silk (thread) to weave their first bonds
VOTE_COST = 1           # pulses a peer stakes to cast one vote
SILK_PER_BOND = 1       # silk a proposer spins into a proposed bond
PROPOSER_BASE_REWARD = 2
VOTER_CONFIRM_REWARD = 1
USEFULNESS_EXP_BASE = 2
MAX_USEFULNESS_BONUS = 64
ROUND_REWARD_BANK_PLS = 1_000_000
# A confirmed knit pays from the staked vote-pot and from a transparent per-round
# protocol reward bank. The exponential usefulness bonus grows with confirming
# peers, capped so a local classroom cannot mint absurd balances by accident.


class FaucetError(RuntimeError):
    pass


@dataclass
class Player:
    """A learner: a real knitweb account (free pulses) + free silk to weave with."""

    name: str
    node: AccountNode
    silk: int = FAUCET_SILK
    roblox_id: str | None = None     # set for players bridged in from the Roblox counterpart

    @classmethod
    def join(cls, name: str, *, roblox_id: str | None = None) -> "Player":
        """Open the faucet: a fresh account seeded with free pulses + free silk (dev/test)."""
        return cls(
            name=name,
            node=AccountNode(genesis_balances={"PLS": FAUCET_PULSES}),
            silk=FAUCET_SILK,
            roblox_id=roblox_id,
        )

    @classmethod
    def from_roblox(
        cls, roblox_id: str, name: str | None = None,
        *, pulses: int = FAUCET_PULSES, silk: int = FAUCET_SILK,
    ) -> "Player":
        """A **stable** knitweb account for a unique Roblox wallet ID.

        The same Roblox player always maps to the same knitweb account (derived
        deterministically from the id), so the two-way bridge can weave their votes and
        carry their balances across sync cycles. ``pulses``/``silk`` seed the account —
        pass the player's *persisted* balance to continue it, or the faucet default for a
        first-seen player.
        """
        import hashlib

        from knitweb.core import crypto

        priv = hashlib.sha256(f"molgang:roblox:{roblox_id}".encode()).hexdigest()
        pub = crypto.public_from_private(priv)
        node = AccountNode(priv=priv, pub=pub, genesis_balances={"PLS": pulses})
        return cls(name=name or f"roblox:{roblox_id}", node=node,
                   silk=silk, roblox_id=str(roblox_id))

    @classmethod
    def from_device(
        cls, device_id: str, name: str | None = None,
        *, pulses: int = FAUCET_PULSES, silk: int = FAUCET_SILK,
    ) -> "Player":
        """A **stable** knitweb wallet for a unique device id (e.g. a phone's persistent id).

        The same device always maps to the same PLS wallet, so a player can leave and rejoin
        the bar from their phone and find their account. Derived deterministically from the id.
        """
        import hashlib

        from knitweb.core import crypto

        priv = hashlib.sha256(f"molgang:device:{device_id}".encode()).hexdigest()
        pub = crypto.public_from_private(priv)
        node = AccountNode(priv=priv, pub=pub, genesis_balances={"PLS": pulses})
        return cls(name=name or "player", node=node, silk=silk)

    # -- views -------------------------------------------------------------
    @property
    def address(self) -> str:
        return self.node.address

    @property
    def pulses(self) -> int:
        return self.node.balance("PLS")

    @property
    def fiber_cid(self) -> str:
        """CID of the player's latest Fiber (their newest account-state commitment)."""
        return self.node.braid.head.cid

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"Player({self.name}, {self.pulses} PLS, {self.silk} silk)"


@dataclass
class Vote:
    voter: Player
    verdict: quorum.Verdict
    knit_id: str            # the real Knit that carried the staked pulse


@dataclass
class Round:
    """One knit up for peer validation — a chemistry ``bond`` or a free brainstorm ``term``."""

    proposer: Player
    escrow: AccountNode                     # neutral pot that holds staked vote-pulses
    reward_bank: AccountNode = field(
        default_factory=lambda: AccountNode(genesis_balances={"PLS": ROUND_REWARD_BANK_PLS})
    )
    bond: Bond | None = None                # set for a chemistry knit (has ground truth)
    term: str | None = None                 # set for a free brainstorm knit (peer consensus)
    votes: list[Vote] = field(default_factory=list)
    _clock: int = 0
    settled: bool = False
    outcome: quorum.Outcome | None = None

    @property
    def label(self) -> str:
        return self.bond.formula if self.bond else (self.term or "?")

    def _tick(self) -> int:
        self._clock += 1
        return self._clock


def honest_verdict(bond: Bond) -> quorum.Verdict:
    """How a peer who actually knows chemistry votes."""
    return quorum.Verdict.CONFIRM if chemistry.is_correct(bond) else quorum.Verdict.MISMATCH


def propose(proposer: Player, formula: str, name: str) -> Round:
    """Spin silk into a proposed chemistry bond and open a validation round."""
    if proposer.silk < SILK_PER_BOND:
        raise FaucetError(f"{proposer.name} is out of silk — visit the faucet")
    proposer.silk -= SILK_PER_BOND
    bond = Bond.propose(formula, name)
    return Round(proposer=proposer, escrow=AccountNode(), bond=bond)


def propose_term(proposer: Player, term: str) -> Round:
    """Spin silk into a free brainstorm **term** (peer consensus, no chemistry ground truth)."""
    if proposer.silk < SILK_PER_BOND:
        raise FaucetError(f"{proposer.name} is out of silk — visit the faucet")
    proposer.silk -= SILK_PER_BOND
    return Round(proposer=proposer, escrow=AccountNode(), term=term.strip())


def cast_vote(rnd: Round, voter: Player, verdict: quorum.Verdict | None = None) -> Vote:
    """A peer stakes one pulse (a real Knit into escrow) and records a verdict.

    ``verdict=None`` ⇒ the peer votes honestly from real chemistry (NPC / default).
    """
    if rnd.settled:
        raise RuntimeError("round already settled")
    if voter.address == rnd.proposer.address:
        raise RuntimeError("a proposer cannot vote on their own bond")
    if voter.pulses < VOTE_COST:
        raise FaucetError(f"{voter.name} has no pulses left to vote")
    if verdict is None:
        verdict = honest_verdict(rnd.bond)
    # the vote IS a real Knit: stake VOTE_COST pulses into the round escrow
    knit = voter.node.transfer_to(rnd.escrow, "PLS", VOTE_COST, rnd._tick())
    vote = Vote(voter=voter, verdict=verdict, knit_id=knit.id)
    rnd.votes.append(vote)
    return vote


@dataclass
class Settlement:
    outcome: quorum.Outcome
    result: quorum.QuorumResult
    woven: bool
    reward: int
    voter_rewards: int
    silk_reward: int
    woven_fiber_cid: str | None


def usefulness_bonus(confirms: int) -> int:
    """Exponential PLS reward for useful work confirmed by other players."""
    if confirms <= 0:
        return 0
    return min(MAX_USEFULNESS_BONUS, USEFULNESS_EXP_BASE ** confirms - 1)


def _pay_reward(rnd: Round, player: Player, amount: int) -> None:
    if amount <= 0:
        return
    rnd.reward_bank.transfer_to(player.node, "PLS", amount, rnd._tick())


def settle(rnd: Round) -> Settlement:
    """Tally the staked verdicts with the real BFT quorum and weave (or refund)."""
    if rnd.settled:
        raise RuntimeError("round already settled")
    result = quorum.tally(v.verdict for v in rnd.votes)
    pot = rnd.escrow.balance("PLS")
    woven, reward, voter_rewards, silk_reward, fiber_cid = False, 0, 0, 0, None

    if result.releases:
        # Useful, peer-confirmed work earns enough to keep playing: the proposer
        # gets the vote pot, restored silk, a base PLS reward, and an exponential
        # usefulness bonus based on confirming peer votes.
        if pot:
            rnd.escrow.transfer_to(rnd.proposer.node, "PLS", pot, rnd._tick())
        silk_reward = SILK_PER_BOND
        rnd.proposer.silk += silk_reward
        protocol_reward = PROPOSER_BASE_REWARD + usefulness_bonus(result.confirms)
        _pay_reward(rnd, rnd.proposer, protocol_reward)
        reward = pot + protocol_reward

        # Confirming voters did useful validation work. Refund their stake and
        # pay fresh PLS, so voting on useful work is net-positive.
        for v in rnd.votes:
            if v.verdict is quorum.Verdict.CONFIRM:
                _pay_reward(rnd, v.voter, VOTE_COST + VOTER_CONFIRM_REWARD)
                voter_rewards += VOTE_COST + VOTER_CONFIRM_REWARD

        woven = True
        fiber_cid = rnd.proposer.fiber_cid
    else:
        # not confirmed (wrong bond, or no quorum) → refund every voter's pulse.
        for v in rnd.votes:
            if rnd.escrow.balance("PLS") >= VOTE_COST:
                rnd.escrow.transfer_to(v.voter.node, "PLS", VOTE_COST, rnd._tick())

    rnd.settled = True
    rnd.outcome = result.outcome
    return Settlement(
        outcome=result.outcome, result=result, woven=woven,
        reward=reward, voter_rewards=voter_rewards, silk_reward=silk_reward,
        woven_fiber_cid=fiber_cid,
    )


# ── Spirals ────────────────────────────────────────────────────────────────
# A spider weaves spirals, not chains. Players weave a spiral of links together at a table:
# an **auxiliary** spiral (a draft guide track) while it gathers staked pulses, becoming a
# sticky **capture** spiral once peers confirm it with a BFT quorum — it captures a Fiber and
# pays the staked pulse-pot to its weaver. One settle weaves every link → the web grows fast.
CONTAGION_SILK = 1          # silk a correct-side backer earns back on a captured spiral
MAX_SPIRAL_LEN = 7          # links per spiral (anti-spam cap)
MIN_SPIRAL_VOTERS = 3       # a spiral needs ≥3 backers before it can be captured
AUXILIARY = "auxiliary"     # draft, non-sticky guide spiral (still gathering pulses)
CAPTURE = "capture"         # confirmed, sticky spiral that captured a Fiber


def spiral_silk_cost(n_links: int) -> int:
    """Escalating silk to weave a spiral of ``n_links`` (1 + i//3 per added link)."""
    return sum(1 + i // 3 for i in range(n_links))


@dataclass
class SpiralRound:
    leader: Player
    escrow: AccountNode                     # one pot for the whole spiral's staked pulses
    links: list[dict]                       # ordered parsed link dicts (kind='link')
    votes: list[Vote] = field(default_factory=list)
    _clock: int = 0
    settled: bool = False
    captured: bool = False
    outcome: quorum.Outcome | None = None

    @property
    def state(self) -> str:
        return CAPTURE if self.captured else AUXILIARY

    @property
    def length(self) -> int:
        return len(self.links)

    @property
    def stake_per_vote(self) -> int:
        return VOTE_COST * len(self.links)    # a backer stakes one pulse per link

    def _tick(self) -> int:
        self._clock += 1
        return self._clock


def honest_spiral_verdict(links) -> quorum.Verdict:
    """How a peer who knows chemistry votes on a whole spiral: confirm iff every link is sound."""
    return (quorum.Verdict.CONFIRM if all(chemistry.link_is_sound(link) for link in links)
            else quorum.Verdict.MISMATCH)


def propose_spiral(leader: Player, links: list[dict]) -> SpiralRound:
    """Lay the auxiliary spiral: spend escalating silk to open a spiral of 2..7 links."""
    if not 2 <= len(links) <= MAX_SPIRAL_LEN:
        raise ValueError(f"a spiral needs 2..{MAX_SPIRAL_LEN} links")
    cost = spiral_silk_cost(len(links))
    if leader.silk < cost:
        raise FaucetError(f"{leader.name} needs {cost} silk to weave this spiral")
    leader.silk -= cost
    return SpiralRound(leader=leader, escrow=AccountNode(), links=list(links))


def cast_spiral_vote(sr: SpiralRound, voter: Player, verdict: quorum.Verdict | None = None) -> Vote:
    """Back a spiral: stake VOTE_COST pulses per link into the escrow (real Knit) + a verdict."""
    if sr.settled:
        raise RuntimeError("spiral already settled")
    if voter.address == sr.leader.address:
        raise RuntimeError("the leader cannot back their own spiral")
    stake = sr.stake_per_vote
    if voter.pulses < stake:
        raise FaucetError(f"{voter.name} needs {stake} pulses to back this spiral")
    if verdict is None:
        verdict = honest_spiral_verdict(sr.links)
    knit = voter.node.transfer_to(sr.escrow, "PLS", stake, sr._tick())
    vote = Vote(voter=voter, verdict=verdict, knit_id=knit.id)
    sr.votes.append(vote)
    return vote


@dataclass
class SpiralSettlement:
    outcome: quorum.Outcome
    result: "quorum.QuorumResult"
    captured: bool
    reward: int
    leader_fiber_cid: str | None
    voter_silk: dict
    pls_staked: int


def settle_spiral(sr: SpiralRound, *, threshold: int | None = None) -> SpiralSettlement:
    """Tally with the real BFT quorum (optional reputation ``threshold``). On confirm the spiral
    becomes a sticky capture spiral: the whole pot pays the leader + correct backers earn
    contagion silk; otherwise every backer is fully refunded (integer-exact). pouw is untouched."""
    if sr.settled:
        raise RuntimeError("spiral already settled")
    result = quorum.tally((v.verdict for v in sr.votes), threshold=threshold)
    pot = sr.escrow.balance("PLS")
    captured, reward, fiber, voter_silk = False, 0, None, {}
    if result.releases:
        if pot:
            sr.escrow.transfer_to(sr.leader.node, "PLS", pot, sr._tick())
        reward, captured, fiber = pot, True, sr.leader.fiber_cid
        for v in sr.votes:
            if v.verdict == quorum.Verdict.CONFIRM:
                v.voter.silk += CONTAGION_SILK
                voter_silk[v.voter.address] = voter_silk.get(v.voter.address, 0) + CONTAGION_SILK
    else:
        for v in sr.votes:
            if sr.escrow.balance("PLS") >= sr.stake_per_vote:
                sr.escrow.transfer_to(v.voter.node, "PLS", sr.stake_per_vote, sr._tick())
    sr.settled, sr.captured, sr.outcome = True, captured, result.outcome
    return SpiralSettlement(outcome=result.outcome, result=result, captured=captured,
                            reward=reward, leader_fiber_cid=fiber, voter_silk=voter_silk,
                            pls_staked=pot)
