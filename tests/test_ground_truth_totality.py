"""#108 — the graded ground truth is total: every entry validates, tiers cover all."""
from molgang.chemistry import ELEMENTS, MOLECULES, TIERS, Bond, is_correct, parse_formula, tier_of


def test_every_molecule_round_trips_and_validates():
    for formula, (name_en, _nl) in MOLECULES.items():
        assert parse_formula(formula), formula
        assert is_correct(Bond.propose(formula, name_en)), formula


def test_tier_of_is_total_over_ground_truth_and_none_for_unknowns():
    for key in list(ELEMENTS) | set(MOLECULES) if isinstance(list(ELEMENTS), set) else set(ELEMENTS) | set(MOLECULES):
        assert tier_of(key) in TIERS, key
    assert tier_of("XyzZy") is None
    assert tier_of("") is None


def test_school_set_breadth():
    """#108 asks the elementary-to-high-school set: sanity floor on breadth."""
    assert len(ELEMENTS) >= 30 and len(MOLECULES) >= 45
    # representative everyday entries exist and are graded
    assert tier_of("NaHCO3") == "middle" and tier_of("CH3COOH") == "high"
    assert tier_of("Cu") == "middle" and tier_of("Ne") == "elementary"
