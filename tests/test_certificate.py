"""PoUW Certificate PDF engine tests — a valid PDF whose text layer carries the wallet.

Runs against the real knitweb package + a real molgang Bar.

    PYTHONPATH=src:/path/to/pulse/src python3 -m pytest -q
"""

from __future__ import annotations

import secrets

import pytest

from molgang.bar import Bar, Session
from molgang.certificate import certificate_for_node, make_pouw_certificate
from molgang.game import FAUCET_PULSES, Player

pypdf = pytest.importorskip("pypdf")  # text-layer assertions need a PDF reader


def _text(path: str) -> str:
    reader = pypdf.PdfReader(path)
    assert len(reader.pages) >= 1
    return "\n".join(p.extract_text() for p in reader.pages)


def _pdf_text(data: bytes) -> str:
    import io

    reader = pypdf.PdfReader(io.BytesIO(data))
    assert len(reader.pages) >= 1
    return "\n".join(p.extract_text() for p in reader.pages)


def _is_pdf(path: str) -> bytes:
    with open(path, "rb") as fh:
        data = fh.read()
    assert data.startswith(b"%PDF-"), "not a PDF"
    assert len(data) > 800, "PDF suspiciously small"
    return data


def test_make_certificate_is_valid_pdf_with_all_wallet_fields(tmp_path):
    addr = "pls1examplewalletaddr"
    pub = "02" + "ab" * 16
    priv = "cd" * 32
    out = str(tmp_path / "cert.pdf")

    ret = make_pouw_certificate(
        address=addr, public_key=pub, private_key=priv, include_private_key=True, pulses_used=42,
        work_summary={"knits_woven": 5, "spirals_captured": 2, "votes_cast": 11},
        provenance={"ual": "did:dkg:knitweb/bafyexample", "nodes": 9, "edges": 4,
                    "verified": True},
        out_path=out, holder="Edwin (dev)")
    assert ret == out
    _is_pdf(out)

    txt = _text(out)
    # the wallet — public key, address, AND the (intentionally exposed) private key
    assert pub in txt
    assert addr in txt
    assert priv in txt
    # the headline pulses-used figure
    assert "PULSES USED" in txt
    assert "42 PLS" in txt
    # the sensitive-private-key warning is present
    assert "SENSITIVE" in txt and "PRIVATE KEY" in txt


def test_make_certificate_public_mode_redacts_private_key(tmp_path):
    out = str(tmp_path / "cert-public.pdf")
    make_pouw_certificate(
        address="pls1pub", public_key="02ff", private_key="aa" * 16, pulses_used=3,
        work_summary={"terms_proposed": 1}, out_path=out)
    txt = _text(out)
    assert "bb" not in txt
    assert "PUBLIC MODE: private key redacted for safe distribution" in txt
    assert "aa" * 16 not in txt
    # work table + provenance + header
    assert "PROOF OF USEFUL WORK CERTIFICATE" in txt
    assert "Terms proposed" in txt


def test_pulses_used_is_clamped_non_negative(tmp_path):
    out = str(tmp_path / "c.pdf")
    make_pouw_certificate(address="pls1x", public_key="02aa", private_key="bb",
                          pulses_used=-9, work_summary={}, out_path=out)
    txt = _text(out)
    assert "0 PLS" in txt                 # negative clamped to 0
    assert "not yet anchored" in txt.lower() or "not yet" in txt.lower()


def test_certificate_for_a_real_bar_player(tmp_path):
    """End-to-end: a device-wallet player validates real knits, then gets a certificate."""
    bar = Bar(str(tmp_path / "world.json"))
    me = bar.join("Validator", "validator-owl", "periodic", device="dev-test-001")
    # fill the table so peer knits reach a CONFIRMED quorum despite the player's dissent
    while bar._seated_count("periodic") < 6:
        sid = secrets.token_hex(8)
        bar.sessions[sid] = Session(sid=sid, name="bot", avatar="validator-owl",
                                    player=Player.join("bot"), table_id="periodic", bot=True)
    bot_sids = [s.sid for s in bar.sessions.values()
                if s.bot and s.table_id == "periodic"]
    for i in range(6):
        bp = bar.propose(bot_sids[i % len(bot_sids)], ["H2O", "CO2", "NaCl"][i % 3])
        pr = bar.proposals.get(bp.pid)
        if pr and not pr.settled and me.sid not in pr.voters:
            bar.vote(me.sid, bp.pid, "mismatch")    # stakes a real pulse

    d = bar.certificate_data(me.sid)
    assert d["pulses_used"] == FAUCET_PULSES - me.player.pulses
    assert d["pulses_used"] > 0                      # the player really spent pulses
    assert d["work_summary"]["votes_cast"] >= 1
    assert d["provenance"]["ual"].startswith("did:dkg:knitweb/")

    out = str(tmp_path / "player.pdf")
    make_pouw_certificate(
        address=d["address"], public_key=d["public_key"], private_key=d["private_key"],
        include_private_key=True, pulses_used=d["pulses_used"], work_summary=d["work_summary"],
        provenance=d["provenance"], holder=d["holder"], out_path=out)
    _is_pdf(out)
    txt = _text(out)
    assert me.player.node.pub in txt
    assert me.player.node.priv in txt                # private key really exposed (by design)
    assert me.player.node.address in txt
    assert f"{d['pulses_used']} PLS" in txt          # the pulses-used number is rendered


def test_certificate_renders_woven_knits_and_spiral_work(tmp_path):
    """A proposer's certificate shows woven knits + a captured spiral in the work table."""
    bar = Bar(str(tmp_path / "world.json"))
    me = bar.join("Weaver", "laser-maxi", "periodic", device="dev-test-002")
    a = bar.propose(me.sid, "H2O")
    sv = bar.propose_spiral(me.sid, ["H2O -> O2", "O2 -> O3"])
    assert a.woven and sv.captured

    d = bar.certificate_data(me.sid)
    assert d["work_summary"]["knits_woven"] >= 1
    assert d["work_summary"]["spirals_captured"] >= 1

    out = str(tmp_path / "weaver.pdf")
    make_pouw_certificate(
        address=d["address"], public_key=d["public_key"], private_key=d["private_key"],
        include_private_key=True, pulses_used=d["pulses_used"], work_summary=d["work_summary"],
        provenance=d["provenance"], holder=d["holder"], out_path=out)
    txt = _text(out)
    assert "Knits woven" in txt and "Spirals captured" in txt


def test_certificate_for_standalone_knitweb_wallet(tmp_path):
    """A persisted AccountNode (a standalone wallet) can get a certificate."""
    from knitweb.ledger.node import AccountNode
    from knitweb.store import load_node, save_node

    node = AccountNode(genesis_balances={"PLS": FAUCET_PULSES})
    peer = AccountNode()
    node.transfer_to(peer, "PLS", 8, 1)              # spend some pulses -> nonce advances
    path = str(tmp_path / "wallet.json")
    save_node(node, path)
    restored = load_node(path)

    out = str(tmp_path / "wallet-cert.pdf")
    ret = certificate_for_node(restored, out_path=out, faucet_pulses=FAUCET_PULSES,
                               holder="standalone", include_private_key=True)
    assert ret == out
    _is_pdf(out)
    txt = _text(out)
    assert restored.pub in txt
    assert restored.priv in txt
    assert restored.address in txt
    # pulses_used = faucet - balance = 8
    assert f"{FAUCET_PULSES - restored.balance('PLS')} PLS" in txt


def test_api_certificate_endpoint_returns_pdf(tmp_path):
    """POST /api/certificate {sid} returns an application/pdf attachment for the player."""
    import io

    from molgang.webserver import make_handler

    bar = Bar(str(tmp_path / "world.json"))
    me = bar.join("Apiuser", "laser-maxi", "periodic", device="dev-api-001")
    bar.propose(me.sid, "H2O")                        # a little real work

    Handler = make_handler(bar)
    body = ('{"sid": "%s"}' % me.sid).encode()

    class _FakeRequest(io.BytesIO):
        def makefile(self, *a, **k):  # BaseHTTPRequestHandler reads via makefile
            return self

    # Build a raw HTTP POST and let BaseHTTPRequestHandler parse + dispatch it.
    raw = (b"POST /api/certificate HTTP/1.1\r\n"
           b"Content-Type: application/json\r\n"
           b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
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

        def setup(self):  # skip socket setup
            pass

    _H(rfile, wfile)
    out = wfile.getvalue()
    assert b"200" in out.split(b"\r\n", 1)[0]
    assert b"application/pdf" in out
    assert b"Content-Disposition: attachment" in out
    # the response body is a real PDF
    assert b"%PDF-" in out
    idx = out.index(b"%PDF-")
    txt = _pdf_text(out[idx:])
    assert "PUBLIC MODE: private key redacted for safe distribution" in txt
    assert me.player.node.priv not in txt

    # explicit bearer mode prints private key
    body = ('{"sid": "%s", "mode": "bearer"}' % me.sid).encode()
    raw = (b"POST /api/certificate HTTP/1.1\r\n"
           b"Content-Type: application/json\r\n"
           b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
    rfile = io.BytesIO(raw)
    wfile = io.BytesIO()
    _H(rfile, wfile)
    out = wfile.getvalue()
    assert b"200" in out.split(b"\r\n", 1)[0]
    idx = out.index(b"%PDF-")
    txt = _pdf_text(out[idx:])
    assert me.player.node.priv in txt
