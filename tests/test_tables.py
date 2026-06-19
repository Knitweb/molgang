"""Dynamic tables and table naming ownership behavior."""

from __future__ import annotations

import pytest

from molgang.bar import Bar


def test_auto_add_table_when_all_existing_tables_are_full(tmp_path):
    bar = Bar(str(tmp_path / "w.json"))
    # Keep the defaults intentionally small to force full tables and predictable growth.
    for t in bar.tables.values():
        t.seats = 3

    player = bar.join("Latecomer")
    bar.sit(player.sid, "periodic")

    assert len(bar.tables) == 4
    assert player.table_id != "periodic"
    assert player.table_id.startswith("table-")

    new_table = bar.tables[player.table_id]
    assert new_table.name.startswith("Table ")


def test_table_name_can_be_set_by_a_namer_and_resets_when_owner_leaves(tmp_path):
    bar = Bar(str(tmp_path / "w.json"))
    owner = bar.join("Owner")
    bar.sit(owner.sid, "periodic")

    bar.rename_table(owner.sid, "periodic", "Owner's Lounge")
    assert bar.tables["periodic"].name == "Owner's Lounge"
    assert bar.tables["periodic"].owner_sid == owner.sid

    witness = bar.join("Witness", table_id="periodic")
    with pytest.raises(RuntimeError):
        bar.rename_table(witness.sid, "periodic", "Witness's Lounge")

    bar.leave(owner.sid)

    assert bar.tables["periodic"].owner_sid is None
    assert bar.tables["periodic"].name == "Periodic Bar"
    bar.rename_table(witness.sid, "periodic", "Witness's Lounge")
    assert bar.tables["periodic"].name == "Witness's Lounge"
    assert bar.tables["periodic"].owner_sid == witness.sid


def test_state_exposes_whether_current_table_name_can_change(tmp_path):
    bar = Bar(str(tmp_path / "w.json"))
    owner = bar.join("Namer")
    bar.sit(owner.sid, "periodic")

    st = bar.state(owner.sid)
    t = next(x for x in st["tables"] if x["id"] == "periodic")
    assert t["can_rename"] is True

    other = bar.join("Other", table_id="periodic")
    st2 = bar.state(other.sid)
    p = next(x for x in st2["tables"] if x["id"] == "periodic")
    assert p["can_rename"] is True
