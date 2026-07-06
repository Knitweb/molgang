"""Fable-verified fact knitting (facts.py): sourced, checked, provenance-tagged weaving.

All tests are pure (no network): they exercise the verification math, the ledger CIDs, and
the weave provenance with in-memory fixtures shaped exactly like the cached PubChem rows.
"""
import json

from molgang import facts
from molgang.world import World

TABLE = [
    {"AtomicNumber": "1", "Symbol": "H", "Name": "Hydrogen", "AtomicMass": "1.008",
     "GroupBlock": "Nonmetal", "Period": "1", "StandardState": "Gas",
     "ElectronConfiguration": "1s1"},
    {"AtomicNumber": "6", "Symbol": "C", "Name": "Carbon", "AtomicMass": "12.011",
     "GroupBlock": "Nonmetal", "Period": "2", "StandardState": "Solid",
     "ElectronConfiguration": "[He]2s2 2p2"},
    {"AtomicNumber": "8", "Symbol": "O", "Name": "Oxygen", "AtomicMass": "15.999",
     "GroupBlock": "Nonmetal", "Period": "2", "StandardState": "Gas",
     "ElectronConfiguration": "[He]2s2 2p4"},
]
MASSES = facts.atomic_masses(TABLE)

WATER = {"CID": 962, "MolecularFormula": "H2O", "MolecularWeight": "18.015",
         "Title": "Water"}
GLUCOSE = {"CID": 5793, "MolecularFormula": "C6H12O6", "MolecularWeight": "180.16",
           "Title": "D-Glucose"}
WRONG_MASS = {"CID": 999999, "MolecularFormula": "H2O", "MolecularWeight": "44.01",
              "Title": "NotWater"}  # CO2's mass on water's formula -> must be rejected
CHARGED = {"CID": 123, "MolecularFormula": "C6H5O7-3", "MolecularWeight": "189.1",
           "Title": "Citrate"}     # charge notation -> skipped, never guessed


def test_parse_flat_formula_and_rejects():
    assert facts.parse_flat_formula("C6H12O6", MASSES) == {"C": 6, "H": 12, "O": 6}
    for bad in ("", "H2O.2H2O", "(NH4)2SO4", "C6H5O7-3", "Xx2"):
        try:
            facts.parse_flat_formula(bad, MASSES)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} should have been rejected")


def test_verify_compound_accepts_true_and_rejects_false_mass():
    ok, check = facts.verify_compound(WATER, MASSES)
    assert ok and check["composition"] == {"H": 2, "O": 1}
    assert check["rel_err"] <= facts.MW_REL_TOL

    ok, check = facts.verify_compound(WRONG_MASS, MASSES)
    assert not ok and check["rel_err"] > facts.MW_REL_TOL  # the check is real, not cosmetic

    ok, check = facts.verify_compound(CHARGED, MASSES)
    assert not ok and check.get("reason")  # unparseable -> rejected with a reason


def test_every_fact_names_source_and_verifier():
    all_facts = facts.element_facts(TABLE) + facts.compound_facts(
        [WATER, GLUCOSE, WRONG_MASS], MASSES)
    assert all_facts
    for f in all_facts:
        assert f["verified_by"] == "claude-fable-5"
        assert f["source"]["name"].startswith("PubChem")
        assert f["source"]["url"].startswith("https://pubchem.ncbi.nlm.nih.gov/")
        assert isinstance(f["verified"], bool) and f["method"]


def test_rejected_facts_are_ledgered_but_never_woven(tmp_path):
    all_facts = facts.compound_facts([WATER, WRONG_MASS], MASSES)
    rejected = [f for f in all_facts if not f["verified"]]
    assert rejected  # WRONG_MASS produced auditable rejects

    ledger = tmp_path / "ledger.jsonl"
    n = facts.write_ledger(all_facts, str(ledger))
    assert n == len(all_facts)  # ledger holds accepted AND rejected

    world = World(path=None)
    woven = facts.weave_facts(all_facts, world)
    assert woven == len(all_facts) - len(rejected)  # only verified facts reach the fabric


def test_woven_edges_carry_fable_provenance():
    world = World(path=None)
    wfacts = facts.compound_facts([WATER], MASSES)
    facts.weave_facts(wfacts, world)
    by_fact = {facts.fact_cid(f): f for f in wfacts}
    tagged = [i for i in world.items if i.kind == "link"]
    assert tagged
    for item in tagged:
        assert item.by == "fable:claude-fable-5"       # verifier visible on every edge
        assert item.fiber_cid in by_fact                # edge -> ledger record resolves
        assert by_fact[item.fiber_cid]["source"]["url"]  # ... and that record names the source


def test_fact_cid_deterministic_and_content_bound():
    f1 = facts.compound_facts([WATER], MASSES)[0]
    f2 = json.loads(json.dumps(f1))          # round-trip -> same content, same cid
    assert facts.fact_cid(f1) == facts.fact_cid(f2)
    f2["object"] = "tampered"
    assert facts.fact_cid(f1) != facts.fact_cid(f2)  # any change -> new provenance cid


def test_element_facts_shape():
    efacts = facts.element_facts(TABLE)
    rels = {f["relation"] for f in efacts}
    assert {"is-named", "is-a", "in-period"} <= rels
    assert all(f["verified"] for f in efacts)
