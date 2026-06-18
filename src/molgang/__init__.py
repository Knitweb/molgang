"""MOLGANG — a peer-to-peer chemistry (scheikunde) learning game on the Knitweb.

Bonds are Knits, molecules are Fibers, peers validate with pulses (a `pouw.quorum`),
and newcomers start with free silk + pulses from the faucet. See `game.py` for the map.
"""

from __future__ import annotations

from . import chemistry, game
from .chemistry import Bond
from .game import Player, Round, Settlement, Vote, cast_vote, honest_verdict, propose, settle

__all__ = [
    "chemistry", "game", "Bond", "Player", "Round", "Settlement", "Vote",
    "cast_vote", "honest_verdict", "propose", "settle",
]

__version__ = "0.1.0"
