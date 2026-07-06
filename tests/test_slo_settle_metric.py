"""The quorum-settle latency metric records on a woven knit (#125)."""

import re

from molgang import metrics
from molgang.bar import Bar


def _settle_count() -> int:
    m = re.search(r"molgang_quorum_settle_seconds_count\s+(\d+)", metrics.REGISTRY.render())
    return int(m.group(1)) if m else 0


def test_settle_records_quorum_settle_latency():
    before = _settle_count()
    bar = Bar()
    s = bar.join("Tester", "x")
    table = bar.state(s.sid)["tables"][0]["id"]
    bar.sit(s.sid, table)
    # correct chemistry → seeded bots reach quorum → woven → settle observed
    bar.propose(s.sid, "H2O")
    woven = bar.state(s.sid)["my_knits"]["knits"]
    assert any(k["woven"] for k in woven), "expected the H2O knit to weave"
    assert _settle_count() > before, "settle should record molgang_quorum_settle_seconds"
