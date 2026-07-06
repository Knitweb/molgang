"""Sprint D: Chemistry lens, JSON-LD export, KG sharding, multilingual lang tags, Prometheus metrics."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys

import pytest

from molgang.chemistry import ChemistryLens, MOLECULES, ELEMENTS
from molgang.world import VALID_LANGS, WovenItem, validate_lang, World


# ---------------------------------------------------------------------------
# D3: ChemistryLens
# ---------------------------------------------------------------------------


def test_chemistry_lens_known_compound():
    lens = ChemistryLens()
    results = lens.react("H2O")
    assert len(results) >= 1
    node = next(r for r in results if r["node"] == "H2O")
    assert node["formula"] == "H2O"
    assert node["name_en"] == "Water"
    assert node["name_nl"] == "Water"
    assert node["type"] == "molecule"


def test_chemistry_lens_unknown_returns_empty():
    lens = ChemistryLens()
    assert lens.react("NOTACOMPOUND") == []
    assert lens.react("") == []


def test_chemistry_lens_multilingual_label():
    lens = ChemistryLens()
    results = lens.react("NaCl")
    assert any("NaCl" in str(r) for r in results)
    node = next(r for r in results if r.get("node") == "NaCl")
    assert node["name_en"] and node["name_nl"]


def test_chemistry_lens_reaction_edge_present():
    """H2O appears in combustion reactions — should surface as a neighbor."""
    lens = ChemistryLens()
    results = lens.react("H2O")
    mol_result = next(r for r in results if r["node"] == "H2O")
    assert len(mol_result["neighbors"]) > 0


def test_chemistry_lens_hub_node_has_degree():
    """H2O is a hub molecule — should have multiple neighbors."""
    lens = ChemistryLens()
    results = lens.react("H2O")
    mol_result = next(r for r in results if r["node"] == "H2O")
    assert len(mol_result["neighbors"]) > 1


# ---------------------------------------------------------------------------
# D7: JSON-LD export
# ---------------------------------------------------------------------------


def test_jsonld_context_present(tmp_path):
    world = World(str(tmp_path / "world.json"))
    doc = world.to_jsonld()
    assert "@context" in doc
    assert "knitweb" in doc["@context"]
    assert "@graph" in doc


def test_jsonld_fiber_id_from_cid(tmp_path):
    world = World(str(tmp_path / "world.json"))
    # Inject a woven item directly
    world.items.append(WovenItem(
        kind="term", by="tester", fiber_cid="abc123", confirmations=1, term="H2O"
    ))
    doc = world.to_jsonld()
    ids = [n["@id"] for n in doc["@graph"]]
    assert any("abc123" in i for i in ids)


def test_jsonld_voter_list_structure(tmp_path):
    world = World(str(tmp_path / "world.json"))
    world.items.append(WovenItem(
        kind="term", by="alice", fiber_cid="cid1", confirmations=2, term="CO2"
    ))
    doc = world.to_jsonld()
    node = doc["@graph"][0]
    assert node["knitweb:by"] == "alice"
    assert node["knitweb:confirmations"] == 2


# ---------------------------------------------------------------------------
# D8: KG sharding
# ---------------------------------------------------------------------------


def test_kg_shard_count():
    import networkx as nx
    from molgang.graphx import shard
    g = nx.DiGraph()
    g.add_nodes_from(range(16))
    shards = shard(g, n_shards=4)
    assert len(shards) == 4
    total_nodes = sum(s.number_of_nodes() for s in shards)
    assert total_nodes == 16


def test_kg_merge_is_lossless():
    import networkx as nx
    from molgang.graphx import shard, merge_shards
    g = nx.DiGraph()
    g.add_nodes_from(["a", "b", "c", "d"])
    g.add_edges_from([("a", "b"), ("c", "d")])
    shards = shard(g, n_shards=4)
    merged = merge_shards(shards)
    assert set(merged.nodes()) == set(g.nodes())


def test_kg_shard_stable_across_python_hash_seeds():
    """Shard ownership must be identical on peers with different hash seeds."""
    code = """
import json
import networkx as nx
from molgang.graphx import shard
g = nx.DiGraph()
g.add_nodes_from(["H2O", "CO2", "NaCl", "V2O5", "oxygen"])
assignments = {}
for index, sg in enumerate(shard(g, n_shards=4)):
    for node in sg.nodes():
        assignments[node] = index
print(json.dumps(assignments, sort_keys=True))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(["src", env.get("PYTHONPATH", "")])
    env["PYTHONHASHSEED"] = "1"
    first = subprocess.check_output([sys.executable, "-c", code], text=True, env=env)
    env["PYTHONHASHSEED"] = "2"
    second = subprocess.check_output([sys.executable, "-c", code], text=True, env=env)
    assert json.loads(first) == json.loads(second)


# ---------------------------------------------------------------------------
# D9: Multilingual lang validation
# ---------------------------------------------------------------------------


def test_valid_lang_accepted():
    for lang in VALID_LANGS:
        assert validate_lang(lang) == lang


def test_invalid_lang_raises():
    with pytest.raises(ValueError, match="unsupported lang"):
        validate_lang("xx")


def test_default_lang_is_en():
    assert validate_lang(None) == "en"
    assert validate_lang("") == "en"


def test_rtl_lang_ar_accepted():
    assert validate_lang("ar") == "ar"


# ---------------------------------------------------------------------------
# D1: Prometheus metrics endpoint
# ---------------------------------------------------------------------------


def _make_metrics_request(bar, relay=None):
    from molgang.webserver import make_handler
    Handler = make_handler(bar, relay=relay)

    raw = b"GET /metrics HTTP/1.1\r\nHost: localhost\r\n\r\n"
    rfile = io.BytesIO(raw)
    wfile = io.BytesIO()

    class _H(Handler):
        def __init__(self, rfile, wfile):
            self.rfile = rfile
            self.wfile = wfile
            self.client_address = ("127.0.0.1", 0)
            self.requestline = ""
            self.request_version = "HTTP/1.1"
            self.command = ""
            self.handle_one_request()

        def setup(self):
            pass

    _H(rfile, wfile)
    return wfile.getvalue().decode("utf-8", errors="replace")


def test_metrics_returns_200(tmp_path):
    from molgang.bar import Bar
    bar = Bar(str(tmp_path / "w.json"))
    resp = _make_metrics_request(bar)
    assert "200" in resp.split("\r\n", 1)[0]


def test_metrics_content_type(tmp_path):
    from molgang.bar import Bar
    bar = Bar(str(tmp_path / "w.json"))
    resp = _make_metrics_request(bar)
    assert "text/plain" in resp


def test_metrics_gauge_names(tmp_path):
    from molgang.bar import Bar
    bar = Bar(str(tmp_path / "w.json"))
    resp = _make_metrics_request(bar)
    assert "molgang_players_total" in resp
    assert "molgang_pulses_circulating" in resp
    assert "molgang_faucet_day" in resp
    assert "molgang_relay_queue_depth" in resp


def test_metrics_relay_depth_zero_when_no_relay(tmp_path):
    from molgang.bar import Bar
    bar = Bar(str(tmp_path / "w.json"))
    resp = _make_metrics_request(bar, relay=None)
    assert "molgang_relay_queue_depth 0" in resp


def test_jsonld_embeds_origintrail_provenance(tmp_path):
    """#107: the JSON-LD export is provenance-linked — UAL + state_root embedded."""
    from molgang.bar import Bar
    bar = Bar(str(tmp_path / "world.json"))
    me = bar.join("Weaver", "laser-maxi", "periodic", device="dev-jsonld-1")
    bar.propose(me.sid, "H2O")                    # weave something real
    doc = bar.world.to_jsonld()
    prov = doc["knitweb:provenance"]
    assert prov["knitweb:ual"] and prov["knitweb:ual"].startswith("did:dkg:knitweb/")
    assert prov["knitweb:stateRoot"]
    assert prov["knitweb:stateRoot"] == bar.world.anchor()["state_root"]
    assert "prov" in doc["@context"]


def test_jsonld_term_nodes_carry_lang_and_base_direction(tmp_path):
    """#107: term nodes carry lang + W3C base direction for multilingual webs."""
    world = World(str(tmp_path / "world.json"))
    world.items.append(WovenItem(
        kind="term", by="t", fiber_cid="cid-en", confirmations=1, term="water", lang="en"))
    world.items.append(WovenItem(
        kind="term", by="t", fiber_cid="cid-ar", confirmations=1, term="ماء", lang="ar"))
    nodes = {n["@id"]: n for n in world.to_jsonld()["@graph"]}
    assert nodes["knitweb:fiber/cid-en"]["knitweb:lang"] == "en"
    assert nodes["knitweb:fiber/cid-en"]["knitweb:baseDirection"] == "ltr"
    assert nodes["knitweb:fiber/cid-ar"]["knitweb:baseDirection"] == "rtl"
