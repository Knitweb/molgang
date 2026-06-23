"""Tests for molgang.webnode.contract — the JS<->Python postMessage contract."""

import pytest

from molgang.webnode.contract import (
    CONTRACT_VERSION,
    MSG_ERROR,
    MSG_EVENT,
    MSG_HELLO,
    MSG_READY,
    MSG_RESULT,
    MSG_RPC,
    ContractError,
    assert_jsonsafe,
    make_error,
    make_event,
    make_hello,
    make_ready,
    make_result,
    parse_rpc,
)


def test_contract_version_contains_webnode():
    assert "webnode" in CONTRACT_VERSION


def test_make_hello_has_required_keys():
    msg = make_hello(seed="abc123")
    assert msg["type"] == MSG_HELLO
    assert msg["seed"] == "abc123"
    assert msg["contract"] == CONTRACT_VERSION


def test_make_hello_accepts_seams():
    msg = make_hello(seed="abc", seams={"now": 1000, "id_proof_now": 500})
    assert msg["seams"]["now"] == 1000


def test_make_ready_has_required_keys():
    msg = make_ready(contract=CONTRACT_VERSION, identity={"address": "0xabc", "balance": 1_000_000})
    assert msg["type"] == MSG_READY
    assert msg["identity"]["address"] == "0xabc"


def test_make_result_has_id_and_payload():
    msg = make_result(7, {"pulses": 42})
    assert msg["type"] == MSG_RESULT
    assert msg["id"] == 7
    assert msg["payload"]["pulses"] == 42
    assert msg["ok"] is True


def test_make_result_rejects_bool_id():
    with pytest.raises(ContractError):
        make_result(True, {})


def test_make_error_has_id_and_message():
    msg = make_error(3, "bad args")
    assert msg["type"] == MSG_ERROR
    assert msg["id"] == 3
    assert "bad" in msg["error"]
    assert msg["ok"] is False


def test_make_error_accepts_none_id():
    msg = make_error(None, "boot failed")
    assert msg["id"] is None


def test_make_event_has_kind():
    msg = make_event("woven", {"cid": "bafk..."})
    assert msg["type"] == MSG_EVENT
    assert msg["kind"] == "woven"


def test_make_event_rejects_unknown_kind():
    with pytest.raises(ContractError):
        make_event("not_a_real_event", {})


def test_parse_rpc_extracts_id_method_args():
    rpc_msg = {"type": MSG_RPC, "id": 5, "method": "state", "args": {"sid": "abc"}}
    rpc_id, method, args = parse_rpc(rpc_msg)
    assert rpc_id == 5
    assert method == "state"
    assert args == {"sid": "abc"}


def test_parse_rpc_rejects_non_rpc():
    with pytest.raises(ContractError):
        parse_rpc({"type": MSG_READY, "contract": CONTRACT_VERSION, "identity": {}})


def test_parse_rpc_rejects_unknown_method():
    with pytest.raises(ContractError):
        parse_rpc({"type": MSG_RPC, "id": 1, "method": "explode"})


def test_assert_jsonsafe_passes_basic_types():
    assert assert_jsonsafe(42) == 42
    assert assert_jsonsafe("hello") == "hello"
    assert assert_jsonsafe(None) is None
    assert assert_jsonsafe([1, 2, 3]) == [1, 2, 3]
    assert assert_jsonsafe({"a": 1, "b": [True, None]}) == {"a": 1, "b": [True, None]}


def test_assert_jsonsafe_rejects_fractional_float():
    with pytest.raises(ContractError):
        assert_jsonsafe(3.14)


def test_assert_jsonsafe_coerces_whole_float():
    # Whole-number floats (display timestamps from the injected integer clock) are coerced.
    assert assert_jsonsafe(100.0) == 100


def test_assert_jsonsafe_rejects_float_in_nested_list():
    with pytest.raises(ContractError):
        assert_jsonsafe({"balance": [1, 2.5, 3]})


def test_assert_jsonsafe_rejects_float_in_nested_dict():
    with pytest.raises(ContractError):
        assert_jsonsafe({"price": 0.5})
