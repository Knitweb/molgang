"""FIBER **TENSION** — the make-or-break factor for traversal (v1, integer-only).

Every woven link (an *edge / fiber*) is a **tensioned thread**, not a passive link. A
traversing pulse (an agent / a local SLM) rides the fibers; the tension on a fiber decides
whether the trip is fast, slow, or *breaks*. This module is the pure-integer core of that
idea — it carries **no floats anywhere** so two nodes always compute the identical value
(consensus-safe, matching molgang's integer ``Edge`` weight rule).

THREE STATES (bands on a derived integer ``T`` = *tautness*, scale ``S = 1000``):

* **TAUT / optimal**  — ``T >= TAUT_T`` — well-voted, anchor-backed, fresh. Minimal
  resistance: routing *prefers* it, the pulse travels fast + cheap. Explorer = cyan.
* **SLACK / low**     — ``T < SLACK_T`` — outdated / un-voted. The pulse is absorbed, the
  path "wobbles"; these loops are *pruned*. Explorer = dim red/grey.
* **NEUTRAL / forming** — in between — a normal fiber still gathering votes.
* **CONTESTED → SNAP** — ``tension >= SNAP_CRIT`` — a conflict between an agent's data and
  the existing logic crosses a critical threshold: the fiber **snaps** (Quality Gate), the
  bad-data weaver is identified + slashed, the broken fiber is removed. Explorer = orange.

Per edge we store a small set of INTEGER counters + one timestamp (see :class:`Fiber`):
``confirms`` (positive votes / corroborations — this IS molgang's existing ``weight``),
``mismatches`` (counter-evidence + negative votes), ``anchor_rel`` (data-anchor reliability,
the formula denominator), ``anchor_ts`` (epoch secs of the last anchor refresh, drives aging).

Derived integers (recomputed on READ, never mutating the stored counters):

* ``tautness(f, now) -> T``  in ``0..S`` — NARS-style confidence over net positive
  evidence, anchored by reliability and aged by ``anchor_ts``. Headline routing signal.
* ``tension(f) -> int``      scaled by ``S`` — owner's contested signal, the snap driver:
  ``mismatches * S / (anchor_rel + 1)``.
* ``friction(f) -> int``     scaled by ``S`` — ``mismatches * S / (confirms + 1)``.
* ``edge_cost(f, now) -> int`` — ``COST_MAX - T + BASE``: taut ≈ free, slack ≈ expensive,
  so a least-cost path is the *most-taut* path (what ``graphx`` minimises).

The division rule everywhere: **scale-then-integer-divide** — ``(num * S) // den`` with a
``+1`` denominator guard and a single truncate-toward-zero rounding mode. Computed AFTER the
multiply (never divide first) so no precision is lost; deterministic on every CPU.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# -- fixed-point scale + tuning constants (all integer; config-tunable) -------
S = 1000                 # fixed-point scale: derived values live in 0..S "milli-units"
COST_MAX = S             # ceiling for the inverse-tautness routing cost
BASE = 1                 # min edge cost so Dijkstra never sees a 0/negative weight

R_MAX = 1000             # cap on anchor_rel (reliability) — overflow invariant
DEFAULT_ANCHOR_REL = 100  # reliability when an anchor is present but unscored
COUNTER_CAP = 1_000_000  # cap on confirms / mismatches — overflow invariant

K_ANCHOR = 1             # NARS evidence-horizon constant (bigger → slower climb to TAUT)
HALF_LIFE_SECS = 7 * 24 * 3600   # one age-step per ~week of staleness
DECAY_K = 1              # how hard each age-step pushes T down (linear, integer)

# band cutoffs on the S=1000 tautness scale -----------------------------------
TAUT_T = 700             # T >= 700 → TAUT (conducting fiber)
SLACK_T = 300            # T < 300  → SLACK (wobble / prune-eligible)
HYST = 50                # hysteresis: leave TAUT only below TAUT_T - HYST (anti-flap)

# the snap (Quality Gate) trigger on the tension scale -------------------------
SNAP_CRIT = 1500         # tension >= 1500 → CONTESTED → snap

# state labels
TAUT = "taut"
NEUTRAL = "neutral"
SLACK = "slack"
CONTESTED = "contested"


@dataclass
class Fiber:
    """The integer tension state carried on one woven edge (fiber).

    ``confirms`` is molgang's existing ``weight`` (``World.link`` sets weight = confirm
    count) — kept as the positive-evidence counter. Everything derived (T, tension, cost)
    is a pure function of these fields, recomputed on read.
    """

    confirms: int = 1            # positive votes / corroborating traversals (== weight)
    mismatches: int = 0          # counter-evidence + negative votes
    anchor_rel: int = DEFAULT_ANCHOR_REL  # reliability of the backing data-anchor (0..R_MAX)
    anchor_ts: int = 0           # epoch secs the anchor/evidence was last refreshed
    weaver: str = ""             # node id / pubkey of the weaver (the slashable owner)
    collateral_id: str = ""      # pouw stake handle bonded at weave-time (follow-up)
    snapped: bool = False        # tombstoned by a snap → excluded from the active fabric

    def clamped(self) -> "Fiber":
        """A copy with counters/reliability clamped to the documented overflow invariants."""
        return Fiber(
            confirms=_clamp(self.confirms, 0, COUNTER_CAP),
            mismatches=_clamp(self.mismatches, 0, COUNTER_CAP),
            anchor_rel=_clamp(self.anchor_rel, 0, R_MAX),
            anchor_ts=max(0, int(self.anchor_ts)),
            weaver=self.weaver, collateral_id=self.collateral_id, snapped=self.snapped,
        )

    def as_dict(self) -> dict:
        return {"confirms": self.confirms, "mismatches": self.mismatches,
                "anchor_rel": self.anchor_rel, "anchor_ts": self.anchor_ts,
                "weaver": self.weaver, "collateral_id": self.collateral_id,
                "snapped": self.snapped}


def _clamp(v: int, lo: int, hi: int) -> int:
    return lo if v < lo else hi if v > hi else int(v)


def age_steps(f: Fiber, now: int) -> int:
    """Integer staleness in HALF_LIFE_SECS units (no floats / no exp).

    ``(now - anchor_ts) // HALF_LIFE_SECS`` — decay enters the tautness denominator
    linearly, a monotonic rational-decay curve that is cheap + fully deterministic. An
    edge with no anchor timestamp (``anchor_ts == 0``) or a future timestamp ages 0.
    """
    if f.anchor_ts <= 0 or now <= f.anchor_ts:
        return 0
    return (int(now) - int(f.anchor_ts)) // HALF_LIFE_SECS


def tautness(f: Fiber, now: int = 0) -> int:
    """TAUTNESS ``T`` in ``0..S`` — the headline routing signal (integer NARS confidence).

    ``net = max(0, confirms - mismatches)`` (net positive evidence)::

        T = net*anchor_rel*S / (net*anchor_rel + K_ANCHOR*S + ageSteps*DECAY_K*S)

    T near ``S`` = TAUT (lots of agreeing, anchor-backed, fresh evidence); T near ``0`` =
    SLACK. A snapped fiber has T = 0 (it is gone from the fabric). Decay is applied here at
    read time and never mutates the stored counters (preserves the historical record).
    """
    f = f.clamped()
    if f.snapped:
        return 0
    net = f.confirms - f.mismatches
    if net <= 0 or f.anchor_rel <= 0:
        return 0
    steps = age_steps(f, now)
    num = net * f.anchor_rel * S
    den = net * f.anchor_rel + K_ANCHOR * S + steps * DECAY_K * S
    return num // den          # truncate toward zero — the one canonical rounding mode


def tension(f: Fiber) -> int:
    """TENSION (owner's contested signal, the SNAP driver), scaled by ``S``.

    ``mismatches * S / (anchor_rel + 1)`` — counter-evidence over reliability (the ``+1``
    guards div-by-zero). High mismatches against weak reliability → high tension → snap.
    """
    f = f.clamped()
    if f.snapped:
        return 0
    return (f.mismatches * S) // (f.anchor_rel + 1)


def friction(f: Fiber) -> int:
    """FRICTION (owner's separate gate), scaled by ``S``: ``mismatches * S / (confirms + 1)``.

    Negative-evidence vs corroboration. Feeds the snap decision, but ``tension`` (the
    reliability-denominated signal) is the primary SNAP_CRIT trigger so a well-anchored
    fiber resists snapping even under some negative votes.
    """
    f = f.clamped()
    return (f.mismatches * S) // (f.confirms + 1)


def is_snap(f: Fiber) -> bool:
    """True when the fiber is over the Quality Gate — ``tension >= SNAP_CRIT``."""
    return (not f.snapped) and tension(f) >= SNAP_CRIT


def band(f: Fiber, now: int = 0, *, prev: str | None = None) -> str:
    """Classify a fiber into TAUT | NEUTRAL | SLACK | CONTESTED.

    CONTESTED (snap) takes precedence — independent of T, a fiber can have decent T but
    still snap on hard counter-evidence against weak reliability. Otherwise the band is a
    cutoff on T. ``prev`` enables hysteresis: a fiber already TAUT only demotes below
    ``TAUT_T - HYST`` (so a boundary fiber doesn't flap band on every vote).
    """
    if f.snapped:
        return CONTESTED
    if tension(f) >= SNAP_CRIT:
        return CONTESTED
    t = tautness(f, now)
    taut_floor = TAUT_T - HYST if prev == TAUT else TAUT_T
    if t >= taut_floor:
        return TAUT
    if t < SLACK_T:
        return SLACK
    return NEUTRAL


def edge_cost(f: Fiber, now: int = 0) -> int:
    """Routing cost ``COST_MAX - T + BASE`` (integer) — what NetworkX minimises.

    TAUT (T≈S) → cost ≈ 1 (near-free); NEUTRAL (T≈S/2) → ≈ S/2; SLACK (T≈0) → ≈ S
    (expensive → the path-finder avoids it unless there is no taut route). A snapped fiber
    returns ``None`` (caller excludes it from the graph — infinite cost by absence). The
    riding agent's token budget maps linearly to path cost, so a taut route literally costs
    fewer tokens.
    """
    if f.snapped:
        return None
    return COST_MAX - tautness(f, now) + BASE


def state(f: Fiber, now: int = 0, *, prev: str | None = None) -> dict:
    """One bundle of every derived integer for an edge — for the explorer / API."""
    return {
        "tautness": tautness(f, now),
        "tension": tension(f),
        "friction": friction(f),
        "cost": edge_cost(f, now),
        "band": band(f, now, prev=prev),
        "confirms": f.confirms,
        "mismatches": f.mismatches,
        "anchor_rel": f.anchor_rel,
        "snapped": f.snapped,
    }


# -- weave / vote ops (mutate the stored counters; T is recomputed on read) ----
def vote_up(f: Fiber, *, now: int | None = None) -> Fiber:
    """A positive vote / corroborating traversal: ``confirms += 1`` (monotonic climb)."""
    f.confirms = _clamp(f.confirms + 1, 0, COUNTER_CAP)
    if now is not None:
        f.anchor_ts = int(now)          # a fresh corroboration re-anchors recency
    return f


def vote_down(f: Fiber) -> Fiber:
    """A negative vote / counter-evidence: ``mismatches += 1`` (T down, tension up)."""
    f.mismatches = _clamp(f.mismatches + 1, 0, COUNTER_CAP)
    return f
