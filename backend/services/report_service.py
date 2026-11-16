"""Concise PDF financial outlook report (ReportLab)."""
from __future__ import annotations

import io
from typing import Optional
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

TONE_COLORS = {
    "favorable": colors.HexColor("#047857"),
    "unfavorable": colors.HexColor("#B91C1C"),
    "uncertain": colors.HexColor("#B45309"),
    "neutral": colors.HexColor("#334155"),
}


def _p(text: Optional[str], style) -> Paragraph:
    return Paragraph(escape(text or "").replace("\n", "<br/>"), style)


def build_report(outlook: dict, investigation_name: str, sources: dict[str, dict]) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=0.8 * inch, rightMargin=0.8 * inch,
                            topMargin=0.7 * inch, bottomMargin=0.7 * inch,
                            title=f"Financial Outlook: {outlook.get('company_name')}")
    ss = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=ss["BodyText"], fontSize=9.5, leading=13, alignment=TA_LEFT)
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10.5, textColor=colors.HexColor("#475569"))
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=18, leading=22, alignment=TA_LEFT, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=12, leading=15, spaceBefore=10, spaceAfter=4,
                        textColor=colors.HexColor("#0F172A"))
    story = []
    cur = outlook.get("currency") or "USD"

    story.append(_p("Project Sentinel: Financial Outlook", h1))
    story.append(_p(
        f"{outlook.get('company_name')} | Data through {outlook.get('as_of_label')} | Forecast period: "
        f"{(outlook.get('forecast_window') or {}).get('label') or 'n/a'} ({outlook.get('horizon_months')} months) | "
        f"Currency: {cur}", small))
    story.append(Spacer(1, 8))

    ov = outlook["overall"]
    tone = TONE_COLORS.get(ov["tone"], colors.black)
    label_style = ParagraphStyle("lbl", parent=body, fontSize=14, leading=18, textColor=tone, fontName="Helvetica-Bold")
    story.append(_p(f"Overall outlook: {ov['label']}", label_style))
    story.append(_p(ov["headline"], body))
    if ov.get("qualifier"):
        story.append(_p(ov["qualifier"], small))

    # Company forecast
    story.append(_p("Company forecast", h2))
    rows = [["Metric", "Outlook", "Assessment"]]
    for line in outlook.get("company", []) + outlook.get("company_other", []):
        assess = {"favorable": "Favorable", "unfavorable": "Unfavorable", "neutral": "Neutral"}.get(line.get("tone"), "Uncertain")
        rows.append([_p(line["label"], body), _p(_words(line["display"]), body), _p(assess, body)])
    t = Table(rows, colWidths=[1.7 * inch, 3.6 * inch, 1.4 * inch])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(t)

    # Projects
    if outlook.get("projects"):
        story.append(_p("Project outlook", h2))
        rows = [["Project", "Estimated final cost", "Budget", "Variance", "Outlook"]]
        for p in outlook["projects"]:
            rows.append([_p(p["project"], body), _p(p["eac_text"], body), _p(p["budget_text"], body),
                         _p(p["variance_text"], body), _p(p["outlook"], body)])
        t = Table(rows, colWidths=[1.2 * inch, 1.3 * inch, 1.4 * inch, 1.5 * inch, 1.3 * inch])
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(t)
        for p in outlook["projects"]:
            if p.get("method_label"):
                story.append(_p(f"{p['project']}: estimate uses {p['method_label'].lower()} ({p['method_formula']}).", small))
            if p.get("message"):
                story.append(_p(f"{p['project']}: {p['message']}", small))

    # Reasons
    story.append(_p("Why Sentinel predicts this", h2))
    if outlook.get("why", {}).get("plain_language"):
        story.append(_p(outlook["why"]["plain_language"], body))
        story.append(Spacer(1, 4))
    for i, r in enumerate(outlook.get("reasons", []), start=1):
        refs = _refs(r.get("fact_ids", []), sources)
        story.append(KeepTogether([
            _p(f"{i}. {r['title']}" + (f" ({r['magnitude']})" if r.get("magnitude") else ""), ParagraphStyle("b", parent=body, fontName="Helvetica-Bold")),
            _p(r["text"], body),
            _p(f"Evidence: {r['evidence_type']}, {r['support']}." + (f" Sources: {refs}" if refs else ""), small),
            Spacer(1, 3),
        ]))

    story.append(_p("What could change the outlook", h2))
    for w in outlook.get("what_could_change", []):
        story.append(_p(f"- {w}", body))

    story.append(_p("Key assumptions", h2))
    for a in outlook.get("assumptions", [])[:14]:
        story.append(_p(f"- {a}", body))

    dq = outlook.get("data_quality", {})
    story.append(_p("Data quality and limitations", h2))
    story.append(_p(f"Overall evidence quality: {dq.get('label')} ({dq.get('score')}/100).", body))
    for lim in dq.get("limitations", [])[:8]:
        story.append(_p(f"- {lim}", body))

    review = (outlook.get("agent_review") or {}).get("alex")
    if review:
        story.append(_p("Independent review", h2))
        story.append(_p(f"Reviewer verdict: {review['overall_verdict']}. {review['verdict_reason']}", body))

    story.append(_p("Recommended next step", h2))
    story.append(_p(outlook.get("next_step"), body))

    story.append(_p("Source documents", h2))
    for f in outlook.get("files", []):
        story.append(_p(f"- {f['name']}" + (f" ({f['pages']} pages)" if f.get("pages") else ""), small))
    story.append(Spacer(1, 10))
    story.append(_p(
        "Prepared by Project Sentinel. Forecasts are calculated from the uploaded documents with statistical models and "
        "explicit formulas. They are estimates, not guarantees. Ranges are approximate and based on historical forecast "
        "errors; they are not probabilities. This is a hackathon prototype, not certified financial advice.", small))

    doc.build(story)
    return buf.getvalue()


def _words(display: str) -> str:
    for a, b in (("↑ +", "Up "), ("↓ -", "Down "), ("↑ ", "Up: "), ("↓ ", "Down: "), ("→ ", "Flat: "), ("→", "Flat"), ("? ", "")):
        display = display.replace(a, b)
    return display


def _refs(fact_ids: list[str], sources: dict[str, dict]) -> str:
    labels = []
    for fid in fact_ids[:4]:
        f = sources.get(fid)
        if not f:
            continue
        src = f["source"]
        parts = [src["file_name"]]
        if src.get("page"):
            parts.append(f"p. {src['page']}")
        if src.get("sheet"):
            parts.append(f"sheet {src['sheet']}")
        if src.get("row"):
            parts.append(f"row {src['row']}")
        labels.append(" ".join(parts))
    return "; ".join(dict.fromkeys(labels))
