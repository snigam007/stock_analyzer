import io
import re
import logging
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
)

logger = logging.getLogger(__name__)

def clean_text(s: str) -> str:
    """Sanitize strings for ReportLab XML/HTML parser."""
    if not s:
        return ""
    # Remove emojis that ReportLab standard Helvetica font cannot render
    s = re.sub(r'[^\x00-\x7F]+', '', str(s))
    s = s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return s.strip()

def generate_institutional_advisory_pdf(
    symbol: str,
    stock_name: str,
    sector: str,
    current_price: float,
    signal_data: dict,
    score_data: dict,
    ml_ensemble_data: dict,
    champion_data: dict,
    trade_plan: dict,
    pos_sizing: dict,
    fno_data: dict = None,
    macro_data: dict = None,
) -> bytes:
    """
    Generate an Institutional-Grade Quantitative Equity Research PDF Report.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontSize=18,
        leading=22,
        textColor=colors.HexColor('#0d233a'),
        spaceAfter=4
    )
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontSize=9.5,
        leading=13,
        textColor=colors.HexColor('#555555'),
        spaceAfter=8
    )
    h2_style = ParagraphStyle(
        'Heading2Custom',
        parent=styles['Heading2'],
        fontSize=12,
        leading=15,
        textColor=colors.HexColor('#0052cc'),
        spaceBefore=8,
        spaceAfter=5
    )
    body_style = ParagraphStyle(
        'BodyCustom',
        parent=styles['Normal'],
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor('#222222')
    )
    bold_body = ParagraphStyle(
        'BoldBody',
        parent=body_style,
        fontName='Helvetica-Bold'
    )

    story = []

    # Header Banner
    story.append(Paragraph("<b>INSTITUTIONAL QUANTITATIVE EQUITY RESEARCH NOTE</b>", subtitle_style))
    story.append(Paragraph(f"<b>{clean_text(symbol)}</b> - {clean_text(stock_name)}", title_style))
    date_str = datetime.now().strftime("%B %d, %Y")
    story.append(Paragraph(f"Sector: <b>{clean_text(sector)}</b> | Coverage Date: <b>{date_str}</b> | CMP: <b>INR {current_price:,.2f}</b>", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#0052cc'), spaceBefore=2, spaceAfter=8))

    # 1. Executive Verdict & Factor Scorecard
    sig = clean_text(signal_data.get('signal', 'BUY'))
    score = score_data.get('composite_score', 65.0) or 65.0
    story.append(Paragraph("1. Executive Investment Thesis &amp; Factor Scorecard", h2_style))

    summary_table_data = [
        [
            Paragraph("<b>Primary Quantitative Signal</b>", body_style),
            Paragraph(f"<b><font color='#008000'>{sig}</font></b> (Strength: {clean_text(signal_data.get('signal_strength', 'STRONG'))})", body_style),
            Paragraph("<b>Composite Alpha Score</b>", body_style),
            Paragraph(f"<b>{score:.1f} / 100</b> (Top {100-(score_data.get('universe_percentile') or 80):.0f}%)", body_style),
        ],
        [
            Paragraph("<b>Recommended Entry</b>", body_style),
            Paragraph(f"INR {signal_data.get('buy_price') or current_price:,.2f}", body_style),
            Paragraph("<b>Stop Loss (Strict)</b>", body_style),
            Paragraph(f"INR {signal_data.get('stop_loss') or current_price*0.95:,.2f} ({(signal_data.get('stop_loss_downside_pct') or -5.0):+.1f}%)", body_style),
        ],
        [
            Paragraph("<b>Primary Target 1 (T1)</b>", body_style),
            Paragraph(f"INR {signal_data.get('target_price_1') or current_price*1.05:,.2f} ({(signal_data.get('target_1_upside_pct') or 5.0):+.1f}%)", body_style),
            Paragraph("<b>Runner Target 3 (T3)</b>", body_style),
            Paragraph(f"INR {signal_data.get('target_price_3') or current_price*1.15:,.2f} ({(signal_data.get('target_3_upside_pct') or 15.0):+.1f}%)", body_style),
        ],
        [
            Paragraph("<b>Risk:Reward Ratio</b>", body_style),
            Paragraph(f"<b>{(signal_data.get('risk_reward_ratio') or 2.4):.2f} : 1.0</b>", body_style),
            Paragraph("<b>Beta vs NIFTY 50</b>", body_style),
            Paragraph(f"{(score_data.get('beta') or 1.0):.2f} (Vol: {(score_data.get('volatility_annual') or 0.22)*100:.1f}%/yr)", body_style),
        ]
    ]

    t_summary = Table(summary_table_data, colWidths=[130, 140, 130, 140])
    t_summary.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f7f9fb')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#d0d8e0')),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(t_summary)
    story.append(Spacer(1, 6))

    # 2. Macro Regime Alignment
    if macro_data:
        story.append(Paragraph("2. Macro Market Regime &amp; Environment", h2_style))
        story.append(Paragraph(
            f"Current Macro Regime: <b>{clean_text(macro_data.get('regime', 'RISK-ON'))}</b> (Macro Score: {macro_data.get('macro_score', 60)}/100). "
            f"{clean_text(macro_data.get('summary', ''))} Recommended Global Asset Allocation: <b>Equities {macro_data.get('recommended_allocation', {}).get('Equities %', 70)}% | Gold/Commodities {macro_data.get('recommended_allocation', {}).get('Gold & Commodities %', 15)}% | Cash Buffer {macro_data.get('recommended_allocation', {}).get('Cash & Liquid %', 15)}%</b>.",
            body_style
        ))
        story.append(Spacer(1, 6))

    # 3. 5-Model ML Ensemble Consensus
    story.append(Paragraph("3. 5-Model Machine Learning Ensemble Consensus", h2_style))
    if ml_ensemble_data and ml_ensemble_data.get("models"):
        ml_rows = [
            [Paragraph("<b>ML Algorithm</b>", bold_body), Paragraph("<b>Bullish Probability</b>", bold_body), Paragraph("<b>Model Signal</b>", bold_body), Paragraph("<b>Ensemble Weight</b>", bold_body)]
        ]
        for m in ml_ensemble_data.get("models", []):
            ml_rows.append([
                Paragraph(clean_text(m.get("model", "")), body_style),
                Paragraph(clean_text(m.get("prob_bullish", "")), body_style),
                Paragraph(clean_text(m.get("verdict", "")), body_style),
                Paragraph(clean_text(m.get("weight", "")), body_style),
            ])
        t_ml = Table(ml_rows, colWidths=[180, 120, 140, 100])
        t_ml.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0052cc')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#d0d8e0')),
            ('TOPPADDING', (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ]))
        story.append(t_ml)
        story.append(Paragraph(f"<b>Consensus Verdict:</b> {clean_text(ml_ensemble_data.get('consensus_description', ''))}", body_style))
        story.append(Spacer(1, 6))

    # 4. 3-Tranche Execution Roadmap
    story.append(Paragraph("4. Trade Execution &amp; 3-Tranche Profit Scaling Plan", h2_style))
    if trade_plan:
        tr1 = trade_plan.get('tranche_1', {})
        tr2 = trade_plan.get('tranche_2', {})
        tr3 = trade_plan.get('tranche_3', {})

        tr_data = [
            [Paragraph("<b>Tranche</b>", bold_body), Paragraph("<b>Allocation / Qty</b>", bold_body), Paragraph("<b>Target Price (INR)</b>", bold_body), Paragraph("<b>Est. Duration</b>", bold_body), Paragraph("<b>Execution Action</b>", bold_body)],
            [Paragraph("<b>Tranche 1</b>", body_style), Paragraph(f"{clean_text(tr1.get('pct_label', '40%'))} ({tr1.get('shares', 0)} shs)", body_style), Paragraph(f"INR {(tr1.get('target_price') or 0):,.2f} ({(tr1.get('gain_pct') or 0):+.1f}%)", body_style), Paragraph(clean_text(tr1.get('expected_duration', '3-6 Days')), body_style), Paragraph(clean_text(tr1.get('action', 'Shift SL to Breakeven')), body_style)],
            [Paragraph("<b>Tranche 2</b>", body_style), Paragraph(f"{clean_text(tr2.get('pct_label', '35%'))} ({tr2.get('shares', 0)} shs)", body_style), Paragraph(f"INR {(tr2.get('target_price') or 0):,.2f} ({(tr2.get('gain_pct') or 0):+.1f}%)", body_style), Paragraph(clean_text(tr2.get('expected_duration', '12-20 Days')), body_style), Paragraph(clean_text(tr2.get('action', 'Lock in 2:1 Profit')), body_style)],
            [Paragraph("<b>Tranche 3</b>", body_style), Paragraph(f"{clean_text(tr3.get('pct_label', '25%'))} ({tr3.get('shares', 0)} shs)", body_style), Paragraph(f"INR {(tr3.get('target_price') or 0):,.2f} ({(tr3.get('gain_pct') or 0):+.1f}%)", body_style), Paragraph(clean_text(tr3.get('expected_duration', '35-55 Days')), body_style), Paragraph(clean_text(tr3.get('action', 'Trail on EMA-21')), body_style)],
        ]
        t_tr = Table(tr_data, colWidths=[80, 110, 120, 90, 140])
        t_tr.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0d233a')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#d0d8e0')),
            ('TOPPADDING', (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ]))
        story.append(t_tr)
        if pos_sizing:
            story.append(Paragraph(f"<b>Capital Sizing:</b> Max Risk per Trade: <b>INR {(pos_sizing.get('max_risk_amount') or 1500):,.2f}</b> | Recommended Half-Kelly Exposure: <b>{(pos_sizing.get('half_kelly_pct') or 15):.1f}% of Portfolio</b> ({pos_sizing.get('kelly_shares', 0)} shares).", body_style))
        story.append(Spacer(1, 6))

    # 5. Derivatives & Options Intelligence
    if fno_data:
        story.append(Paragraph("5. Futures &amp; Options (F&amp;O) Derivative Profile", h2_style))
        story.append(Paragraph(
            f"Put-Call Ratio (PCR): <b>{(fno_data.get('pcr') or 1.15):.2f}</b> ({clean_text(fno_data.get('pcr_sentiment', 'Bullish'))}) | OI Buildup: <b>{clean_text(fno_data.get('oi_buildup', 'Long Buildup'))}</b><br/>"
            f"Max Pain Strike: <b>INR {(fno_data.get('max_pain_strike') or current_price):,.2f}</b> | Major Call Wall (Resistance): <b>INR {(fno_data.get('major_resistance_call_wall') or current_price*1.08):,.2f}</b> | Put Wall (Support): <b>INR {(fno_data.get('major_support_put_wall') or current_price*0.92):,.2f}</b> | IV Rank: <b>{(fno_data.get('iv_rank_pct') or 35):.1f}%</b>.",
            body_style
        ))
        story.append(Spacer(1, 6))

    # Disclaimer Footer
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#aaaaaa'), spaceBefore=6, spaceAfter=4))
    story.append(Paragraph(
        "<b>Institutional Disclaimer:</b> This document is generated for professional and quantitative investment research purposes. Past performance of backtested models does not guarantee future results. All investments are subject to market risks. Strict stop-loss risk management must be enforced.",
        ParagraphStyle('Disc', parent=styles['Normal'], fontSize=7.0, leading=9.5, textColor=colors.HexColor('#666666'))
    ))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes