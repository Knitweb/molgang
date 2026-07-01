"""Cross-repo knitweb engine compatibility guard."""

from __future__ import annotations

import json

from knitweb.ledger.node import AccountNode

from molgang.engine_compat import (
    EngineCompatibilityError,
    assert_peer_engine_compatible,
    check_knitweb_compatibility,
    knitweb_requirement,
)
from molgang.relay_sync import WEB_TOPIC, pack, peer_engine_from_body, verify_message
from molgang.webserver import api_version_info
from molgang.world import WovenItem


def test_pyproject_declares_bounded_knitweb_range():
    assert knitweb_requirement() == ">=0.6,<0.7"


def test_exact_engine_version_passes():
    verdict = check_knitweb_compatibility("0.6.0", ">=0.6,<0.7")
    assert verdict.status == "pass"
    assert verdict.compatible is True


def test_patch_drift_warns_inside_range():
    verdict = check_knitweb_compatibility("0.6.1", ">=0.6,<0.7")
    assert verdict.status == "warn"
    assert verdict.compatible is True


def test_incompatible_engine_version_fails():
    verdict = check_knitweb_compatibility("0.7.0", ">=0.6,<0.7")
    assert verdict.status == "fail"
    assert verdict.compatible is False


def test_peer_with_incompatible_engine_is_refused():
    peer = {"knitweb": "0.7.0", "knitweb_requirement": ">=0.7,<0.8"}
    try:
        assert_peer_engine_compatible(peer)
    except EngineCompatibilityError as exc:
        assert "incompatible knitweb engine" in str(exc)
    else:
        raise AssertionError("expected incompatible peer to be refused")


def test_api_version_reports_compatibility_verdict():
    info = api_version_info()
    assert info["knitweb_requirement"] == ">=0.6,<0.7"
    assert info["knitweb_compatibility"]["compatible"] is True


def test_relay_message_advertises_engine_metadata():
    item = WovenItem(kind="term", term="H2O", by="alice", fiber_cid="cid", confirmations=1)
    msg = pack(item, AccountNode.from_seed("engine-compat"), topic=WEB_TOPIC)
    assert verify_message(msg, topic=WEB_TOPIC)
    body = json.loads(msg["body"])
    assert body["_engine"]["knitweb_requirement"] == ">=0.6,<0.7"
    assert peer_engine_from_body(msg["body"]) == body["_engine"]
