"""Proof of Useful Work (PoUW) Certificate — an official PDF for a knitweb wallet.

A PoUW certificate documents a single knitweb/molgang wallet:

  * its **public key**, **address**, and optionally its **PRIVATE key**
    (public mode redacts private material; bearer mode prints it explicitly).
  * **how many pulses were used** — the proof-of-useful-work metric (faucet − remaining);
  * a summary of the *useful work* done (knits woven, spirals captured, votes cast);
  * the OriginTrail provenance UAL (if the wallet's world is anchored) + the issue date.

The single public entry point is :func:`make_pouw_certificate`, which writes a clean,
official-looking A4 PDF with ``fpdf2`` (pure-Python, no native deps) and returns its path.

SECURITY NOTE: public mode redacts the private key. If this certificate
serves as a bearer credential, enable private mode explicitly.
"""

from __future__ import annotations

import datetime as _dt

from fpdf import FPDF

__all__ = ["make_pouw_certificate", "certificate_for_node"]

# Brand palette (RGB)
_INK = (18, 22, 33)            # near-black body text
_MUTED = (110, 118, 134)       # dim captions
_ACCENT = (88, 64, 222)        # knitweb violet (headers / rules)
_DANGER = (176, 28, 44)        # warning red
_DANGER_BG = (252, 233, 235)   # warning panel fill
_PANEL_BG = (244, 245, 250)    # neutral panel fill
_PULSE_BG = (235, 230, 252)    # pulses figure panel

_TITLE = "PROOF OF USEFUL WORK CERTIFICATE"
_SUBTITLE = "knitweb · molgang"

# fpdf2's core fonts are latin-1 only; normalise any stray unicode for safety.
_REPL = {
    "•": "-", "·": "-", "→": "->", "←": "<-", "↔": "<->",
    "–": "-", "—": "-", "‘": "'", "’": "'",
    "“": '"', "”": '"', "⚠": "!", "…": "...",
    "\U0001f3c5": "", "\U0001f578": "", "⛓": "",
}


def _latin(text: str) -> str:
    """Make ``text`` safe for fpdf2's latin-1 core fonts (lossless for our content)."""
    if text is None:
        return ""
    out = str(text)
    for bad, good in _REPL.items():
        out = out.replace(bad, good)
    return out.encode("latin-1", "replace").decode("latin-1")


class _Cert(FPDF):
    def header(self) -> None:
        pass

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(*_MUTED)
        self.cell(
            0, 5,
            _latin("Proof of Useful Work · knitweb/molgang · "
                   "private key shown only in bearer mode"),
            align="C",
        )


def _para(pdf: _Cert, h: float, text: str) -> None:
    """A wrapping paragraph that always starts at the left margin (robust width)."""
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(pdf.w - pdf.l_margin - pdf.r_margin, h, _latin(text),
                   new_x="LMARGIN", new_y="NEXT")


def _rule(pdf: _Cert, color=_ACCENT, h: float = 0.6) -> None:
    pdf.set_draw_color(*color)
    pdf.set_line_width(h)
    y = pdf.get_y()
    pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
    pdf.ln(3)


def _kv(pdf: _Cert, key: str, value: str, *, mono: bool = True) -> None:
    """A label + (wrapping) value row inside a panel."""
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*_MUTED)
    pdf.cell(0, 5, _latin(key.upper()), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Courier" if mono else "Helvetica", "", 10)
    pdf.set_text_color(*_INK)
    _para(pdf, 5, value)
    pdf.ln(1.5)


def make_pouw_certificate(
    *,
    address: str,
    public_key: str,
    private_key: str,
    include_private_key: bool = False,
    pulses_used: int,
    work_summary: dict,
    provenance: dict | None = None,
    out_path: str,
    holder: str | None = None,
    issued: str | None = None,
) -> str:
    """Render a PoUW certificate PDF for one wallet and return ``out_path``.

    Args:
        address:      the wallet's knitweb address (``pls1...``).
        public_key:   the wallet's public key (hex).
        private_key:  the wallet's PRIVATE key (hex).
        include_private_key: print private key in the PDF (bearer mode) or redact it (public mode).
        pulses_used:  the proof-of-useful-work metric (pulses spent doing useful work).
        work_summary: useful-work counts, e.g. ``{"knits_woven", "spirals_captured",
                      "votes_cast", "terms_proposed"}`` (any subset; extra keys are shown too).
        provenance:   optional OriginTrail anchor dict (``{"ual", "state_root", "nodes",
                      "edges", "verified"}`` — as produced by ``World.anchor()``).
        out_path:     where to write the PDF.
        holder:       optional display name for the wallet holder.
        issued:       optional ISO date string (defaults to today, UTC).

    Returns:
        ``out_path``.
    """
    issued = issued or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    pulses_used = max(0, int(pulses_used))

    pdf = _Cert(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(18, 16, 18)
    pdf.add_page()
    pdf.set_title(_latin(f"PoUW Certificate - {address}"))

    # ── Masthead ──────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 19)
    pdf.set_text_color(*_ACCENT)
    pdf.cell(0, 10, _latin(_TITLE), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(*_MUTED)
    pdf.cell(0, 6, _latin(_SUBTITLE), align="C", new_x="LMARGIN", new_y="NEXT")
    if holder:
        pdf.set_font("Helvetica", "I", 10)
        pdf.cell(0, 6, _latin(f"issued to {holder}"), align="C",
                 new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    _rule(pdf)

    # ── PULSES USED — the headline PoUW figure ────────────────────────────
    pdf.set_fill_color(*_PULSE_BG)
    panel_y = pdf.get_y()
    pdf.rect(pdf.l_margin, panel_y, pdf.w - pdf.l_margin - pdf.r_margin, 22, style="F")
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*_MUTED)
    pdf.cell(0, 5, _latin("PULSES USED  (proof-of-useful-work metric)"),
             align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 26)
    pdf.set_text_color(*_ACCENT)
    pdf.cell(0, 11, _latin(f"{pulses_used:,} PLS"), align="C",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)

    # ── Useful-work summary table ─────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*_INK)
    pdf.cell(0, 7, _latin("Useful work performed"), new_x="LMARGIN", new_y="NEXT")

    labels = {
        "knits_woven": "Knits woven",
        "spirals_captured": "Spirals captured",
        "votes_cast": "Votes cast",
        "terms_proposed": "Terms proposed",
        "fibers_advanced": "Fibers advanced",
    }
    rows = []
    for key, label in labels.items():
        if key in work_summary:
            rows.append((label, work_summary[key]))
    # include any extra caller-supplied metrics, preserving insertion order
    for key, val in work_summary.items():
        if key not in labels:
            rows.append((key.replace("_", " ").capitalize(), val))

    col_w = pdf.w - pdf.l_margin - pdf.r_margin
    pdf.set_font("Helvetica", "", 10)
    for i, (label, val) in enumerate(rows):
        pdf.set_fill_color(*(_PANEL_BG if i % 2 == 0 else (255, 255, 255)))
        pdf.set_text_color(*_INK)
        pdf.cell(col_w * 0.7, 7, _latin(f"  {label}"), border=0, fill=True)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(col_w * 0.3, 7, _latin(f"{val}  "), border=0, fill=True,
                 align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
    if not rows:
        pdf.set_text_color(*_MUTED)
        pdf.cell(0, 7, _latin("  (no useful work recorded yet)"),
                 new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # ── Wallet block (public + address) ───────────────────────────────────
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*_INK)
    pdf.cell(0, 7, _latin("Wallet"), new_x="LMARGIN", new_y="NEXT")
    _kv(pdf, "Public key", public_key)
    _kv(pdf, "Address", address)

    # ── PRIVATE KEY — bearer vs public mode ───────────────────────────────
    pdf.ln(1)
    if include_private_key:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*_DANGER)
        pdf.set_fill_color(*_DANGER_BG)
        pdf.cell(0, 8, _latin("  !  SENSITIVE - exposes full wallet control"),
                 fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*_DANGER)
        pdf.cell(0, 5, _latin("PRIVATE KEY"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Courier", "", 10)
        pdf.set_text_color(*_INK)
        _para(pdf, 5, private_key)
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(*_MUTED)
        _para(pdf, 4,
              "Anyone holding this certificate holds the wallet. This is bearer mode "
              "and the private key is intentionally printed.")
    else:
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*_DANGER)
        pdf.set_fill_color(*_DANGER_BG)
        pdf.cell(0, 7, _latin("  PUBLIC MODE: private key redacted for safe distribution"),
                 fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(*_MUTED)
        _para(pdf, 4,
              "For a bearer certificate, request private mode. "
              "This document is safe to share as proof of useful work.")
    pdf.ln(3)

    # ── Provenance (OriginTrail UAL) ──────────────────────────────────────
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*_INK)
    pdf.cell(0, 7, _latin("Provenance"), new_x="LMARGIN", new_y="NEXT")
    if provenance and provenance.get("ual"):
        _kv(pdf, "OriginTrail UAL", str(provenance["ual"]))
        meta = []
        if provenance.get("nodes") is not None:
            meta.append(f"{provenance['nodes']} nodes")
        if provenance.get("edges") is not None:
            meta.append(f"{provenance['edges']} edges")
        if "verified" in provenance:
            meta.append("verified" if provenance["verified"] else "unverified")
        if meta:
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*_MUTED)
            pdf.cell(0, 5, _latin("shared web: " + "  -  ".join(meta)),
                     new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*_MUTED)
        pdf.cell(0, 6, _latin("(not yet anchored to OriginTrail)"),
                 new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    _rule(pdf, color=_MUTED, h=0.3)

    # ── Issue date + seal ─────────────────────────────────────────────────
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_INK)
    pdf.cell(0, 6, _latin(f"Issued: {issued}    ·    Network: knitweb (PLS)"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*_ACCENT)
    pdf.cell(0, 6,
             _latin("SEAL · Proof of Useful Work · woven on the Knitweb"),
             new_x="LMARGIN", new_y="NEXT")

    pdf.output(out_path)
    return out_path


def certificate_for_node(node, *, out_path: str, pulses_used: int | None = None,
                         work_summary: dict | None = None, provenance: dict | None = None,
                         holder: str | None = None, faucet_pulses: int | None = None,
                         include_private_key: bool = False) -> str:
    """Build a PoUW certificate from a knitweb ``AccountNode`` (e.g. a standalone wallet).

    ``pulses_used`` defaults to ``faucet_pulses - node.balance("PLS")`` (clamped >=0) when a
    ``faucet_pulses`` baseline is given, else to the wallet's nonce (its number of settled
    transfers — a transfer-count proxy for work) so a persisted standalone wallet still gets a
    meaningful figure.
    """
    if pulses_used is None:
        if faucet_pulses is not None:
            pulses_used = max(0, faucet_pulses - node.balance("PLS"))
        else:
            pulses_used = max(0, int(getattr(node, "nonce", 0)))
    return make_pouw_certificate(
        address=node.address,
        public_key=node.pub,
        private_key=node.priv,
        include_private_key=include_private_key,
        pulses_used=pulses_used,
        work_summary=work_summary or {"transfers_settled": int(getattr(node, "nonce", 0))},
        provenance=provenance,
        out_path=out_path,
        holder=holder,
    )
