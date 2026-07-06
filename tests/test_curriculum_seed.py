"""#56 — seed the shared fabric with the full chemistry curriculum via real quorum."""
import tempfile
from pathlib import Path

from molgang import chemistry
from molgang.bar import Bar
from molgang.seed import curriculum_knits, seed_bar, seed_world


def test_curriculum_knits_are_derived_purely_from_ground_truth():
    knits = curriculum_knits()
    # every element symbol and every molecule formula is a node knit
    for sym in chemistry.ELEMENTS:
        assert sym in knits
    for formula in chemistry.MOLECULES:
        assert formula in knits
    # composition links + reaction equations are present
    assert any(k.startswith("H2O has ") for k in knits)
    assert any("->" in k for k in knits)                 # a reaction equation
    # deterministic
    assert curriculum_knits() == knits


def test_seeding_weaves_the_whole_curriculum_through_quorum():
    stats = seed_world(world_path=None)
    assert stats["proposed"] == len(curriculum_knits())
    assert stats["woven"] == stats["proposed"]           # NPC quorum confirms all of it
    assert stats["rejected"] == 0
    # a real connected fabric, not isolated nodes
    assert stats["nodes"] >= len(chemistry.ELEMENTS)     # at least every element node
    assert stats["edges"] >= len(chemistry.MOLECULES)    # composition + reaction edges


def test_seed_persists_a_world_the_explorer_can_read(tmp_path):
    world = str(tmp_path / "chem_web.json")
    stats = seed_world(world_path=world)
    assert Path(world).is_file() and stats["woven"] > 100
    # a fresh World over the same file sees the seeded fabric (what the explorer does)
    from molgang.world import World
    reopened = World(world)
    g = reopened.graph()
    assert g["nodes"] == stats["nodes"] and g["edges"] == stats["edges"]


def test_seed_bar_reports_honest_coverage_not_blind_success():
    bar = Bar(world_path=None)
    me = bar.join("S", table_id="periodic", device="d")
    bar.sit(me.sid, "periodic")
    # a valid molecule + a chemically INVALID (unbalanced) reaction, which the NPC
    # bots reject via honest_reaction_verdict — so coverage is reported honestly
    stats = seed_bar(bar, me.sid, ["H2O", "H2 + O2 -> H2O @ spark"])
    assert stats["proposed"] == 2 and stats["woven"] == 1 and stats["rejected"] == 1
    assert stats["rejected"] == stats["proposed"] - stats["woven"]
