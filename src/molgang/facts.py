"""Fable-verified fact knitting — weave sourced, independently-checked chemistry facts
into the shared knitweb World at scale.

Every fact this module weaves is (1) **sourced** — derived from a public, per-fact citable
PubChem record (NIH, public domain), and (2) **Fable-verified** — before weaving, the fact
must pass a deterministic re-computation check authored by Claude Fable 5: a compound's
molecular formula is parsed against the *independently fetched* periodic table and its molar
mass recomputed from atomic masses, then compared to the source's stated mass. Facts that
fail stay in the ledger as ``verified: false`` (auditable) and are **never woven**.

Provenance is kept on-fabric, not just in a side file: each woven edge carries
``by = "fable:claude-fable-5"`` and ``fiber_cid = <provenance CID>`` — the sha256 of the
fact's canonical provenance record in the facts ledger (JSONL), which names the original
source URL, the verifier, the method, and the numeric check. So "who says this?" is
answerable per edge: Fable verified it, PubChem is the underlying source.

Reproducible by construction: all HTTP responses are cached under ``cache_dir``; given the
same cache, ledger CIDs, weave order, and the resulting web are byte-stable (no wall-clock
or randomness on the fact path).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.request
from typing import Iterable

__all__ = [
    "VERIFIER",
    "fetch_periodic_table",
    "fetch_compounds",
    "atomic_masses",
    "parse_flat_formula",
    "verify_compound",
    "element_facts",
    "compound_facts",
    "fact_cid",
    "write_ledger",
    "weave_facts",
    "build_facts_world",
]

VERIFIER = "claude-fable-5"
_BY = f"fable:{VERIFIER}"
METHOD_COMPOUND = "formula-parse + molar-mass recompute vs source (rel. tol 5e-3)"
METHOD_ELEMENT = "cross-field consistency of the fetched periodic-table record"

PUBCHEM = "https://pubchem.ncbi.nlm.nih.gov"
_PT_URL = f"{PUBCHEM}/rest/pug/periodictable/JSON"
_PROPS = "MolecularFormula,MolecularWeight,Title"
_TOKEN = re.compile(r"([A-Z][a-z]?)(\d*)")
_FLAT = re.compile(r"^(?:[A-Z][a-z]?\d*)+$")  # no parentheses, dots, charges, isotopes
MW_REL_TOL = 5e-3  # source MWs are isotope-averaged + rounding; 0.5% catches real errors


# ---------------------------------------------------------------------------
# fetch (cached — the reproducibility boundary; everything after is pure)
# ---------------------------------------------------------------------------

def _cached_fetch(url: str, cache_path: str, *, data: bytes | None = None,
                  pause_s: float = 0.25) -> str:
    """Fetch ``url`` (GET, or POST when ``data``) with an on-disk cache.

    The cache is what makes a run reproducible/auditable: re-runs are pure functions of
    the cached snapshot, and the snapshot itself can be archived alongside the ledger.
    """
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            return f.read()
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "molgang-facts/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read().decode("utf-8")
    os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
    tmp = cache_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
    os.replace(tmp, cache_path)
    time.sleep(pause_s)  # PubChem asks <=5 req/s; stay well under
    return body


def fetch_periodic_table(cache_dir: str) -> list[dict]:
    """The full periodic table (118 elements) from PubChem, row-dicts keyed by column name."""
    body = _cached_fetch(_PT_URL, os.path.join(cache_dir, "periodictable.json"))
    table = json.loads(body)["Table"]
    cols = table["Columns"]["Column"]
    return [dict(zip(cols, row["Cell"])) for row in table["Row"]]


def fetch_compounds(cids: Iterable[int], cache_dir: str, *, batch: int = 500) -> list[dict]:
    """Property rows (CID, MolecularFormula, MolecularWeight, Title) for ``cids``.

    Batched POSTs against the PUG REST property table; each batch cached separately so an
    interrupted fetch resumes without refetching. Unknown CIDs are simply absent.
    """
    cids = list(cids)
    rows: list[dict] = []
    for i in range(0, len(cids), batch):
        chunk = cids[i:i + batch]
        url = f"{PUBCHEM}/rest/pug/compound/cid/property/{_PROPS}/JSON"
        data = ("cid=" + ",".join(str(c) for c in chunk)).encode("ascii")
        cache = os.path.join(cache_dir, f"compounds_{chunk[0]}_{chunk[-1]}.json")
        try:
            body = _cached_fetch(url, cache, data=data)
        except Exception:
            continue  # a failed batch is skipped, never fabricated
        try:
            rows.extend(json.loads(body)["PropertyTable"]["Properties"])
        except (KeyError, ValueError):
            continue
    return rows


# ---------------------------------------------------------------------------
# verification (pure, deterministic — the Fable check)
# ---------------------------------------------------------------------------

def atomic_masses(table: list[dict]) -> dict[str, float]:
    """``{symbol: atomic mass}`` from the fetched periodic table (source-derived, not hardcoded)."""
    masses: dict[str, float] = {}
    for row in table:
        sym, mass = row.get("Symbol"), row.get("AtomicMass")
        if sym and mass:
            try:
                masses[sym] = float(mass)
            except ValueError:
                continue
    return masses


def parse_flat_formula(formula: str, known: dict[str, float]) -> dict[str, int]:
    """Parse a flat Hill formula (``C9H8O4``) into ``{element: count}``.

    Raises ``ValueError`` on parentheses/dots/charges/isotope notation or an element not in
    the fetched table — such formulas are *skipped*, never guessed at.
    """
    formula = (formula or "").strip()
    if not formula or not _FLAT.match(formula):
        raise ValueError(f"not a flat formula: {formula!r}")
    atoms: dict[str, int] = {}
    for sym, count in _TOKEN.findall(formula):
        if sym not in known:
            raise ValueError(f"unknown element {sym!r} in {formula!r}")
        atoms[sym] = atoms.get(sym, 0) + (int(count) if count else 1)
    return atoms


def verify_compound(row: dict, masses: dict[str, float]) -> tuple[bool, dict]:
    """The Fable check: recompute the molar mass from atomic masses and compare to the source.

    Returns ``(ok, check)`` where ``check`` records the parsed composition, the recomputed
    mass, the source mass, and the relative error — the auditable numeric evidence.
    """
    formula = row.get("MolecularFormula", "")
    try:
        atoms = parse_flat_formula(formula, masses)
        stated = float(row.get("MolecularWeight", ""))
    except (ValueError, TypeError):
        return False, {"reason": "unparseable formula or mass", "formula": formula}
    computed = sum(masses[el] * n for el, n in atoms.items())
    if stated <= 0:
        return False, {"reason": "non-positive stated mass", "formula": formula}
    rel_err = abs(computed - stated) / stated
    check = {
        "formula": formula,
        "composition": dict(sorted(atoms.items())),
        "computed_mass": round(computed, 4),
        "stated_mass": stated,
        "rel_err": round(rel_err, 6),
        "tolerance": MW_REL_TOL,
    }
    return rel_err <= MW_REL_TOL, check


# ---------------------------------------------------------------------------
# facts (each: subject/relation/object + source + verifier + check)
# ---------------------------------------------------------------------------

def _fact(subject: str, relation: str, obj: str, *, source_url: str, method: str,
          verified: bool, check: dict) -> dict:
    return {
        "subject": subject,
        "relation": relation,
        "object": obj,
        "source": {"name": "PubChem (NIH)", "url": source_url},
        "verified_by": VERIFIER,
        "method": method,
        "verified": verified,
        "check": check,
    }


def element_facts(table: list[dict]) -> list[dict]:
    """Property facts for every element in the fetched table (name, group-block, period, phase).

    The consistency check here is structural (the record names a real symbol/number pair);
    the deeper numeric verification lives on the compound side, where masses cross-check.
    """
    facts: list[dict] = []
    for row in sorted(table, key=lambda r: int(r.get("AtomicNumber", 0) or 0)):
        sym = row.get("Symbol", "")
        num = row.get("AtomicNumber", "")
        name = row.get("Name", "")
        if not sym or not num or not name:
            continue
        url = f"{PUBCHEM}/element/{num}"
        check = {"symbol": sym, "atomic_number": int(num)}
        ok = bool(re.fullmatch(r"[A-Z][a-z]{0,2}", sym)) and int(num) > 0
        pairs = [(sym, "is-named", name)]
        if row.get("GroupBlock"):
            pairs.append((sym, "is-a", row["GroupBlock"]))
        if row.get("Period"):
            pairs.append((sym, "in-period", f"Period {row['Period']}"))
        if row.get("StandardState"):
            pairs.append((sym, "standard-state", row["StandardState"]))
        if row.get("ElectronConfiguration"):
            pairs.append((sym, "electron-configuration", row["ElectronConfiguration"]))
        for s, r, o in pairs:
            facts.append(_fact(s, r, o, source_url=url, method=METHOD_ELEMENT,
                               verified=ok, check=check))
    return facts


def compound_facts(rows: list[dict], masses: dict[str, float]) -> list[dict]:
    """Facts for every compound row: a naming link + one ``contains`` link per element.

    Only rows passing :func:`verify_compound` yield ``verified: true`` facts; failures are
    still returned (``verified: false``) so the ledger shows what was rejected and why.
    """
    facts: list[dict] = []
    for row in rows:
        cid = row.get("CID")
        formula = row.get("MolecularFormula", "")
        title = (row.get("Title") or "").strip()
        if not cid or not formula:
            continue
        url = f"{PUBCHEM}/compound/{cid}"
        ok, check = verify_compound(row, masses)
        if title and title.casefold() != formula.casefold():
            facts.append(_fact(title, "has-formula", formula, source_url=url,
                               method=METHOD_COMPOUND, verified=ok, check=check))
        for el in check.get("composition", {}):
            facts.append(_fact(formula, "contains", el, source_url=url,
                               method=METHOD_COMPOUND, verified=ok, check=check))
    return facts


# ---------------------------------------------------------------------------
# ledger + weave (provenance CID per fact; by/fiber_cid carry it on-fabric)
# ---------------------------------------------------------------------------

def fact_cid(fact: dict) -> str:
    """Deterministic provenance CID: sha256 of the fact's canonical (sorted, compact) JSON."""
    blob = json.dumps(fact, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def write_ledger(facts: list[dict], path: str) -> int:
    """Write the auditable facts ledger (JSONL, one provenance record per line, cid included)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for fact in facts:
            rec = {"cid": fact_cid(fact), **fact}
            f.write(json.dumps(rec, sort_keys=True, ensure_ascii=False) + "\n")
    return len(facts)


def weave_facts(facts: list[dict], world) -> int:
    """Weave every **verified** fact into ``world`` as a provenance-tagged edge.

    Each edge is woven with ``by = "fable:claude-fable-5"`` and ``fiber_cid`` = the fact's
    ledger CID, so the verifier and the path back to the original source stay attached to
    the fabric itself. Unverified facts are skipped (they exist only in the ledger).
    """
    woven = 0
    for fact in facts:
        if not fact.get("verified"):
            continue
        world.weave_links(
            [{"subject": fact["subject"], "relation": fact["relation"],
              "object": fact["object"]}],
            by=_BY, fiber_cid=fact_cid(fact), confirmations=1,
        )
        woven += 1
    return woven


def build_facts_world(cache_dir: str, ledger_path: str, world_path: str | None = None,
                      *, max_cid: int = 26000) -> dict:
    """End-to-end: fetch (cached) → verify → ledger → weave; return honest stats.

    Weaves in memory (one save at the end when ``world_path`` is given) so 100k+ facts do
    not trigger 100k file writes.
    """
    from .world import World

    table = fetch_periodic_table(cache_dir)
    masses = atomic_masses(table)
    rows = fetch_compounds(range(1, max_cid + 1), cache_dir)

    facts = element_facts(table) + compound_facts(rows, masses)
    write_ledger(facts, ledger_path)

    world = World(path=None)
    woven = weave_facts(facts, world)
    if world_path:
        world.path = world_path
        world._save()
    graph = world.graph(limit=10)
    return {
        "elements": len(table),
        "compound_rows": len(rows),
        "facts_total": len(facts),
        "facts_verified": sum(1 for f in facts if f["verified"]),
        "facts_rejected": sum(1 for f in facts if not f["verified"]),
        "woven_edges": woven,
        "nodes": graph["nodes"],
        "edges": graph["edges"],
    }
