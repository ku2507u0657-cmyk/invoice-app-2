"""
utils/pdf.py — Invoice PDF generation using ReportLab.

Usage
-----
    from utils.pdf import build_invoice_pdf
    pdf_bytes = build_invoice_pdf(invoice, company_name="Acme Ltd.")
"""

import io
from datetime import datetime

from reportlab.lib            import colors
from reportlab.lib.pagesizes  import A4
from reportlab.lib.styles     import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units      import mm
from reportlab.lib.enums      import TA_RIGHT, TA_CENTER, TA_LEFT
from reportlab.platypus       import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether,
)


# ── Colour palette (mirrors the app CSS design tokens) ───────────────────
INK      = colors.HexColor("#1A1714")
INK_2    = colors.HexColor("#4A4540")
INK_3    = colors.HexColor("#8A8480")
ACCENT   = colors.HexColor("#1D4ED8")
GREEN    = colors.HexColor("#16A34A")
GREEN_BG = colors.HexColor("#DCFCE7")
AMBER    = colors.HexColor("#D97706")
AMBER_BG = colors.HexColor("#FEF3C7")
RED      = colors.HexColor("#DC2626")
RED_BG   = colors.HexColor("#FEE2E2")
BG       = colors.HexColor("#F7F6F2")
BORDER   = colors.HexColor("#E4E0D8")
WHITE    = colors.white


def _status_colors(status):
    return {
        "paid":    (GREEN, GREEN_BG),
        "unpaid":  (AMBER, AMBER_BG),
        "overdue": (RED,   RED_BG),
    }.get(status, (INK_2, BG))


def _style(base_name, styles, **kwargs):
    """Create a one-off ParagraphStyle from a base style name."""
    parent = styles.get(base_name, styles["Normal"])
    return ParagraphStyle(
        f"_dyn_{id(kwargs)}",
        parent    = parent,
        textColor = kwargs.pop("color", INK),
        **kwargs,
    )


def build_invoice_pdf(invoice, company_name="InvoiceFlow"):
    """
    Build a polished A4 invoice PDF.

    Parameters
    ----------
    invoice      : Invoice ORM instance (client relationship must be loaded)
    company_name : Business name shown in the header

    Returns
    -------
    bytes : Raw PDF content
    """
    buf    = io.BytesIO()
    styles = getSampleStyleSheet()
    story  = []

    W = A4[0] - 40 * mm   # usable width at 20 mm margins

    doc = SimpleDocTemplate(
        buf,
        pagesize      = A4,
        leftMargin    = 20 * mm,
        rightMargin   = 20 * mm,
        topMargin     = 18 * mm,
        bottomMargin  = 18 * mm,
        title         = f"Invoice {invoice.invoice_number}",
        author        = company_name,
    )

    S = lambda name, **kw: _style(name, styles, **kw)

    # ── Header: company name (left) + "INVOICE" (right) ─────────────────
    hdr = Table([[
        Paragraph(company_name,
                  S("Normal", fontSize=18, fontName="Helvetica-Bold", color=INK)),
        Paragraph("INVOICE",
                  S("Normal", fontSize=28, fontName="Helvetica-Bold",
                    color=ACCENT, alignment=TA_RIGHT)),
    ]], colWidths=[W * 0.55, W * 0.45])
    hdr.setStyle(TableStyle([
        ("VALIGN",          (0, 0), (-1, -1), "BOTTOM"),
        ("BOTTOMPADDING",   (0, 0), (-1, -1), 0),
    ]))
    story.append(hdr)
    story.append(HRFlowable(width="100%", thickness=1, color=BORDER, spaceAfter=8))

    # ── Status badge ─────────────────────────────────────────────────────
    eff_status      = invoice.effective_status
    txt_col, bg_col = _status_colors(eff_status)

    badge = Table(
        [[Paragraph(eff_status.upper(),
                    S("Normal", fontSize=7.5, fontName="Helvetica-Bold",
                      color=txt_col, alignment=TA_CENTER))]],
        colWidths=[28 * mm],
    )
    badge.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), bg_col),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
    ]))

    # Meta column: invoice number, dates, status
    meta_rows = [
        [S("Normal", fontSize=8, color=INK_3),  "Invoice Number",
         S("Normal", fontSize=10, fontName="Helvetica-Bold", alignment=TA_RIGHT),
         invoice.invoice_number],
        [S("Normal", fontSize=8, color=INK_3),  "Issue Date",
         S("Normal", fontSize=9, alignment=TA_RIGHT),
         invoice.created_at.strftime("%d %B %Y")],
        [S("Normal", fontSize=8, color=INK_3),  "Due Date",
         S("Normal", fontSize=9, alignment=TA_RIGHT),
         invoice.due_date.strftime("%d %B %Y")],
    ]
    meta_data = [
        [Paragraph(row[1], row[0]), Paragraph(row[3], row[2])]
        for row in meta_rows
    ] + [[Paragraph("Status", S("Normal", fontSize=8, color=INK_3)), badge]]

    meta_tbl = Table(meta_data, colWidths=[30 * mm, 38 * mm])
    meta_tbl.setStyle(TableStyle([
        ("ALIGN",         (1, 0), (1, -1), "RIGHT"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))

    # Bill-to block
    client     = invoice.client
    bill_lines = [
        Paragraph("BILL TO", S("Normal", fontSize=7.5, fontName="Helvetica-Bold",
                               color=INK_3, leading=12)),
        Paragraph(client.name,
                  S("Normal", fontSize=11, fontName="Helvetica-Bold",
                    color=INK, leading=15)),
    ]
    if client.email:
        bill_lines.append(Paragraph(client.email,
                          S("Normal", fontSize=9, color=INK_2, leading=13)))
    if client.phone:
        bill_lines.append(Paragraph(client.phone,
                          S("Normal", fontSize=9, color=INK_2, leading=13)))
    if client.gst_number:
        bill_lines.append(Paragraph(f"GST: {client.gst_number}",
                          S("Normal", fontSize=8.5, color=INK_3, leading=13)))

    info_tbl = Table(
        [[KeepTogether(bill_lines), meta_tbl]],
        colWidths=[W * 0.52, W * 0.48],
    )
    info_tbl.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(info_tbl)
    story.append(HRFlowable(width="100%", thickness=1, color=BORDER, spaceAfter=12))

    # ── Line-items table ──────────────────────────────────────────────────
    col_w = [W * 0.52, W * 0.10, W * 0.19, W * 0.19]

    def th(text, align=TA_LEFT):
        return Paragraph(text, S("Normal", fontSize=8.5,
                                 fontName="Helvetica-Bold",
                                 color=WHITE, alignment=align))

    def td(text, align=TA_LEFT, bold=False):
        return Paragraph(text, S("Normal", fontSize=9, color=INK_2,
                                 fontName="Helvetica-Bold" if bold else "Helvetica",
                                 alignment=align, leading=13))

    items_data = [
        [th("Description"), th("Qty", TA_CENTER),
         th("Rate", TA_RIGHT), th("Amount", TA_RIGHT)],
        [td(f"Professional Services — {client.name}"),
         td("1", TA_CENTER),
         td(invoice.amount_display, TA_RIGHT),
         td(invoice.amount_display, TA_RIGHT)],
    ]
    items_tbl = Table(items_data, colWidths=col_w, repeatRows=1)
    items_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), INK),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, BG]),
        ("LINEBELOW",     (0, 1), (-1, -1), 0.5, BORDER),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(items_tbl)
    story.append(Spacer(1, 4 * mm))

    # ── Totals block ──────────────────────────────────────────────────────
    label_w  = 44 * mm
    value_w  = 30 * mm
    spacer_w = W - label_w - value_w

    def tot_row(label, value, bold=False, invert=False):
        fn = "Helvetica-Bold" if bold else "Helvetica"
        tc = WHITE if invert else INK
        return [
            Spacer(1, 1),
            Paragraph(label, S("Normal", fontSize=9, fontName=fn,
                               color=tc, alignment=TA_RIGHT)),
            Paragraph(value, S("Normal", fontSize=9, fontName=fn,
                               color=tc, alignment=TA_RIGHT)),
        ]

    totals_data = [
        tot_row("Subtotal (excl. GST)", invoice.amount_display),
        tot_row("GST @ 18%",            invoice.gst_display),
        tot_row("Total Payable",         invoice.total_display, bold=True, invert=True),
    ]
    totals_tbl = Table(totals_data, colWidths=[spacer_w, label_w, value_w])
    totals_tbl.setStyle(TableStyle([
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (1, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (1, 0), (-1, -1), 10),
        ("LEFTPADDING",   (0, 0), (0, -1),  0),
        ("RIGHTPADDING",  (0, 0), (0, -1),  0),
        ("TOPPADDING",    (0, 0), (0, -1),  0),
        ("BOTTOMPADDING", (0, 0), (0, -1),  0),
        ("LINEABOVE",     (1, 0), (-1, 0),  0.75, BORDER),
        ("LINEABOVE",     (1, 2), (-1, 2),  0.75, INK),
        ("BACKGROUND",    (1, 2), (-1, 2),  INK),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(totals_tbl)
    story.append(Spacer(1, 10 * mm))

    # ── Payment notes ─────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.75, color=BORDER,
                            spaceBefore=2, spaceAfter=6))
    story.append(Paragraph("Payment Notes",
                            S("Normal", fontSize=9, fontName="Helvetica-Bold",
                              color=INK_2)))
    story.append(Spacer(1, 3))
    story.append(Paragraph(
        f"Please reference <b>{invoice.invoice_number}</b> when making payment. "
        f"Payment is due by <b>{invoice.due_date.strftime('%d %B %Y')}</b>. "
        "For billing enquiries please reply to this email.",
        S("Normal", fontSize=8.5, color=INK_2, leading=13),
    ))

    # ── Footer ────────────────────────────────────────────────────────────
    story.append(Spacer(1, 8 * mm))
    story.append(HRFlowable(width="100%", thickness=0.75, color=BORDER, spaceAfter=5))
    story.append(Paragraph(
        f"{company_name}  &bull;  "
        f"Generated {datetime.utcnow().strftime('%d %b %Y')}  &bull;  "
        f"{invoice.invoice_number}",
        S("Normal", fontSize=7.5, color=INK_3, alignment=TA_CENTER),
    ))

    doc.build(story)
    return buf.getvalue()
