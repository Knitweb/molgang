"""Steel-slag chemistry pack + Slag Run quest chain (#108, SmartSlag/VANELEX)."""
from molgang import chemistry, quests
from molgang.chemistry import (
    MOLECULES, REACTIONS, Bond, is_correct, parse_equation, reaction_is_balanced, tier_of,
)

SLAG_SET = ("FeO", "Fe2O3", "TiO2", "MnO", "Cr2O3", "V2O3", "V2O5")


def test_slag_oxides_are_known_high_tier_molecules():
    for f in SLAG_SET:
        assert f in MOLECULES, f
        assert tier_of(f) == "high", f
    for sym in ("Ti", "V", "Cr", "Mn"):
        assert sym in chemistry.ELEMENTS
        assert tier_of(sym) == "high"


def test_slag_bonds_validate_like_any_chemistry():
    assert is_correct(Bond.propose("V2O5", "Vanadium(V) oxide"))
    assert is_correct(Bond.propose("Cr2O3", "Chromium(III) oxide"))
    # a wrong atom story for a real formula still fails
    import dataclasses
    fake = dataclasses.replace(Bond.propose("V2O5", "Vanadium(V) oxide"), atoms={"V": 1, "O": 1})
    assert not is_correct(fake)


def test_slag_reactions_are_balanced_curriculum_entries():
    for rid in ("roast-vanadium", "thermite-iron"):
        r = parse_equation(REACTIONS[rid]["equation"])
        assert reaction_is_balanced(r), rid
        assert REACTIONS[rid]["tier"] == "high"
    assert "redox" in chemistry.REACTION_TYPES


def _woven(formulas, by="ellen"):
    return [{"term": f, "by": by} for f in formulas]


def test_slag_run_quest_tracks_the_recovery_chain():
    rows = {r["id"]: r for r in quests.quest_progress(_woven(["FeO", "Fe2O3", "V2O3"]), "ellen")}
    run = rows["slag-run"]
    assert run["scope"] == "set" and run["need"] == 5
    assert run["done"] == 3 and not run["complete"]
    # completing the chain awards the XP exactly once, deterministically
    done = {r["id"]: r for r in quests.quest_progress(
        _woven(["FeO", "Fe2O3", "Cr2O3", "V2O3", "V2O5"]), "ellen")}["slag-run"]
    assert done["complete"] and done["xp_awarded"] == 500


def test_slag_prospector_counts_only_the_listed_oxides():
    rows = {r["id"]: r for r in quests.quest_progress(
        _woven(["FeO", "CaO", "SiO2", "H2O", "NaCl"]), "ellen")}
    p = rows["slag-prospector"]
    assert p["done"] == 3 and p["complete"]          # H2O/NaCl don't count toward the set
    # someone else's weaves never count toward my quest
    other = {r["id"]: r for r in quests.quest_progress(
        _woven(["FeO", "CaO", "SiO2"], by="bob"), "ellen")}["slag-prospector"]
    assert other["done"] == 0
