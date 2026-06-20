from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readme_links_economy_doc():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "[`ECONOMY.md`](ECONOMY.md)" in readme


def test_economy_doc_covers_sources_sinks_and_invariants():
    doc = (ROOT / "ECONOMY.md").read_text(encoding="utf-8")
    required = [
        "PLS Sources",
        "PLS Sinks And Transfers",
        "Silk Sources And Sinks",
        "Reputation",
        "No-NFT Invariants",
        "Settlement Invariants",
        "faucet",
        "reward bank",
        "escrow",
        "integer-only",
    ]
    missing = [text for text in required if text not in doc]
    assert missing == []
