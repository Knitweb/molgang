"""The serverless dapp's engine wheel is present and shippable (#pure-p2p dapp).

The browser shell 404s on boot if web/engine/molgang_engine-*.whl is missing, and
runs a stale engine if it is out of date. This guards presence + freshness of the
committed wheel against the live source: it must contain molgang + knitweb and
their subpackages, built by serverless/build_engine.py.
"""
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WHEEL = ROOT / "serverless" / "web" / "engine" / "molgang_engine-0.0.0-py3-none-any.whl"


def test_engine_wheel_is_committed_and_referenced():
    assert WHEEL.is_file(), "engine wheel missing — run serverless/build_engine.py"
    sw = (ROOT / "serverless" / "web" / "sw.js").read_text(encoding="utf-8")
    peer = (ROOT / "serverless" / "web" / "peer.js").read_text(encoding="utf-8")
    assert WHEEL.name in sw and WHEEL.name in peer   # precached + installed


def test_wheel_bundles_both_engines_with_subpackages():
    names = zipfile.ZipFile(WHEEL).namelist()
    for must in ("molgang/__init__.py", "molgang/game.py", "molgang/chemistry.py",
                 "molgang/webnode/runtime.py", "molgang/webnode/peer.py",
                 "knitweb/__init__.py", "knitweb/ledger/node.py",
                 "knitweb/core/crypto.py", "knitweb/p2p/wire.py", "knitweb/pouw/quorum.py"):
        assert must in names, f"engine wheel missing {must}"


def test_build_script_exists():
    assert (ROOT / "serverless" / "build_engine.py").is_file()
