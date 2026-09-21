#!/usr/bin/env python3
"""Generate capstone professor walkthrough PowerPoint using SMU template."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".pip_packages"))

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

HERE = Path(__file__).resolve().parent
DEFAULT_TEMPLATE = HERE / "smu template.pptx"
FALLBACK_TEMPLATE = Path("/Users/lizliao/Downloads/smu template.pptx")
OUT = HERE / "capstone_walkthrough.pptx"

# SMU template custom layouts (see presentation/smu template.pptx)
LAYOUT_TITLE_SLIDE = 0          # Title Slide (opening)
LAYOUT_CONTENT = 11             # 1_Title and Content — SMU top banner
LAYOUT_SECTION = 12             # 1_Section Header — SMU header strip

# Text colours (readable on white body below SMU banner)
SMU_NAVY = RGBColor(0x00, 0x33, 0x66)
DARK = RGBColor(0x1E, 0x29, 0x3B)
GRAY = RGBColor(0x64, 0x74, 0x8B)
ACCENT = RGBColor(0x00, 0x56, 0xA8)

# Content region below SMU banner (~1.49 in)
CONTENT_TOP = Inches(1.65)
MARGIN_L = Inches(0.65)
CONTENT_W = Inches(12.0)


def resolve_template(path: Path | None) -> Path:
    if path and path.exists():
        return path
    if DEFAULT_TEMPLATE.exists():
        return DEFAULT_TEMPLATE
    if FALLBACK_TEMPLATE.exists():
        return FALLBACK_TEMPLATE
    raise FileNotFoundError(
        f"SMU template not found. Tried: {path}, {DEFAULT_TEMPLATE}, {FALLBACK_TEMPLATE}"
    )


def clear_slides(prs: Presentation) -> None:
    xml = prs.slides._sldIdLst
    for sld_id in list(xml):
        r_id = sld_id.rId
        prs.part.drop_rel(r_id)
        xml.remove(sld_id)


def _textbox(slide, left, top, width, height):
    return slide.shapes.add_textbox(left, top, width, height)


def _set_para(p, text, *, size=16, bold=False, color=DARK, align=PP_ALIGN.LEFT, space_after=8):
    p.text = text
    p.font.size = Pt(size)
    p.font.bold = bold
    p.font.color.rgb = color
    p.alignment = align
    p.space_after = Pt(space_after)


def _fill_bullets(tf, bullets: list[str], size=16):
    tf.clear()
    for i, bullet in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        _set_para(p, bullet, size=size, space_after=10)
        p.level = 0


def add_opening_slide(prs: Presentation, title: str, subtitle: str) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[LAYOUT_CONTENT])
    box = _textbox(slide, MARGIN_L, Inches(2.0), CONTENT_W, Inches(1.8))
    _set_para(box.text_frame.paragraphs[0], title, size=34, bold=True, color=SMU_NAVY)
    sub = _textbox(slide, MARGIN_L, Inches(3.9), CONTENT_W, Inches(1.4))
    _set_para(sub.text_frame.paragraphs[0], subtitle, size=18, color=GRAY)
    foot = _textbox(slide, MARGIN_L, Inches(6.3), CONTENT_W, Inches(0.5))
    _set_para(
        foot.text_frame.paragraphs[0],
        "Capstone Project  ·  Singapore Telco Forum Sentiment Analysis  ·  April 2026",
        size=12,
        color=GRAY,
    )


def add_section_slide(prs: Presentation, section: str, timing: str) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[LAYOUT_SECTION])
    box = _textbox(slide, MARGIN_L, Inches(1.8), CONTENT_W, Inches(1.0))
    _set_para(box.text_frame.paragraphs[0], section, size=30, bold=True, color=SMU_NAVY)
    t = _textbox(slide, MARGIN_L, Inches(2.85), Inches(4), Inches(0.5))
    _set_para(t.text_frame.paragraphs[0], timing, size=16, color=ACCENT)


def add_content_slide(prs: Presentation, title: str, bullets: list[str], subtitle: str = "") -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[LAYOUT_CONTENT])
    y = CONTENT_TOP
    hdr = _textbox(slide, MARGIN_L, y, CONTENT_W, Inches(0.65))
    _set_para(hdr.text_frame.paragraphs[0], title, size=26, bold=True, color=SMU_NAVY)
    y += Inches(0.7)
    if subtitle:
        sub = _textbox(slide, MARGIN_L, y, CONTENT_W, Inches(0.45))
        _set_para(sub.text_frame.paragraphs[0], subtitle, size=13, color=GRAY)
        y += Inches(0.5)
    body = _textbox(slide, MARGIN_L, y, CONTENT_W, Inches(7.5) - y)
    tf = body.text_frame
    tf.word_wrap = True
    _fill_bullets(tf, bullets)


def add_two_column_slide(
    prs: Presentation,
    title: str,
    left_title: str,
    left_items: list[str],
    right_title: str,
    right_items: list[str],
) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[LAYOUT_CONTENT])
    hdr = _textbox(slide, MARGIN_L, CONTENT_TOP, CONTENT_W, Inches(0.6))
    _set_para(hdr.text_frame.paragraphs[0], title, size=26, bold=True, color=SMU_NAVY)
    col_w = Inches(5.7)
    col_top = CONTENT_TOP + Inches(0.75)
    for x, ctitle, items in [(MARGIN_L, left_title, left_items), (Inches(6.9), right_title, right_items)]:
        lt = _textbox(slide, x, col_top, col_w, Inches(0.35))
        _set_para(lt.text_frame.paragraphs[0], ctitle, size=15, bold=True, color=ACCENT)
        box = _textbox(slide, x, col_top + Inches(0.4), col_w, Inches(4.8))
        tf = box.text_frame
        tf.word_wrap = True
        _fill_bullets(tf, [f"• {it}" for it in items], size=14)


def add_table_slide(prs: Presentation, title: str, headers: list[str], rows: list[list[str]]) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[LAYOUT_CONTENT])
    hdr = _textbox(slide, MARGIN_L, CONTENT_TOP, CONTENT_W, Inches(0.55))
    _set_para(hdr.text_frame.paragraphs[0], title, size=24, bold=True, color=SMU_NAVY)
    cols, row_count = len(headers), len(rows) + 1
    table = slide.shapes.add_table(
        row_count, cols, MARGIN_L, CONTENT_TOP + Inches(0.65), CONTENT_W, Inches(0.38 * row_count)
    ).table
    for j, h in enumerate(headers):
        cell = table.cell(0, j)
        cell.text = h
        cell.fill.solid()
        cell.fill.fore_color.rgb = SMU_NAVY
        for p in cell.text_frame.paragraphs:
            p.font.bold = True
            p.font.size = Pt(10)
            p.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    for i, row in enumerate(rows, start=1):
        for j, val in enumerate(row):
            cell = table.cell(i, j)
            cell.text = val
            for p in cell.text_frame.paragraphs:
                p.font.size = Pt(10)
                p.font.color.rgb = DARK


def add_demo_slide(prs: Presentation) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[LAYOUT_CONTENT])
    box = _textbox(slide, MARGIN_L, Inches(2.0), CONTENT_W, Inches(0.8))
    _set_para(box.text_frame.paragraphs[0], "Live Demo", size=32, bold=True, color=SMU_NAVY)
    steps = [
        "1.  python dashboard/generate_dashboard.py",
        "2.  open dashboard/index.html",
        "3.  Walk through: KPIs → Sentiment → Source split → Issues → Brands",
        "4.  (Optional) streamlit run dashboard/app.py",
    ]
    body = _textbox(slide, MARGIN_L, Inches(3.0), CONTENT_W, Inches(3.2))
    _fill_bullets(body.text_frame, steps, size=18)


def add_thankyou_slide(prs: Presentation) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[LAYOUT_CONTENT])
    box = _textbox(slide, MARGIN_L, Inches(2.6), CONTENT_W, Inches(1.0))
    _set_para(box.text_frame.paragraphs[0], "Thank you", size=36, bold=True, color=SMU_NAVY, align=PP_ALIGN.CENTER)
    q = _textbox(slide, MARGIN_L, Inches(3.7), CONTENT_W, Inches(0.6))
    _set_para(q.text_frame.paragraphs[0], "Questions & live dashboard demo", size=20, color=GRAY, align=PP_ALIGN.CENTER)


def build(template_path: Path | None = None) -> Path:
    tpl = resolve_template(template_path)
    prs = Presentation(str(tpl))
    clear_slides(prs)

    add_opening_slide(
        prs,
        "Singapore Telco Forum\nSentiment & Issue Analysis",
        "Scrape → Label → Analyse → Visualise mobile-plan discussions\n(Reddit + HardwareZone)",
    )

    add_content_slide(
        prs,
        "Agenda (~15–20 minutes)",
        [
            "A.  Problem & research goal  (2 min)",
            "B.  End-to-end pipeline  (3 min)",
            "C.  Dataset & mobile topics  (3 min)",
            "D.  Sentiment & issue extraction methods  (4 min)",
            "E.  Results dashboard & key findings  (5 min)",
            "F.  Limitations & next steps  (2 min)",
            "Q&A",
        ],
    )

    add_section_slide(prs, "A.  Problem & Research Goal", "~2 minutes")
    add_content_slide(
        prs,
        "Why this project?",
        [
            "Singapore mobile market: Singtel, StarHub, M1, SIMBA, MVNOs (Giga, Eight, Zym, …)",
            "Customers discuss plans, coverage, and service on public forums — rich unsolicited feedback",
            "Research question: What do forum users say about telcos, and on which topics?",
            "Goal: Build a reproducible pipeline to collect, label, and visualise sentiment + mobile-specific issues",
        ],
        subtitle="Forum data complements surveys: real pain points, launch reactions, switching intent",
    )

    add_section_slide(prs, "B.  End-to-End Pipeline", "~3 minutes")
    add_content_slide(
        prs,
        "Pipeline overview",
        [
            "①  Scrape — Reddit (r/singapore, r/askSingapore) + HardwareZone threads",
            "②  Preprocess — clean text, normalise columns, remove noise",
            "③  Telco labeler — detect brand(s) + VADER / optional LLM sentiment",
            "④  Issue extraction — classify into mobile topic taxonomy",
            "⑤  Dashboard — static HTML report + interactive Streamlit app",
            "",
            "Scripts: scrapers/ → processing/ → models/ → dashboard/",
            "All outputs stored in data/raw/ and data/processed/",
        ],
    )

    add_section_slide(prs, "C.  Dataset & Mobile Topics", "~3 minutes")
    add_two_column_slide(
        prs,
        "Data sources & scale",
        "Sources",
        [
            "Reddit — posts & comments, keyword-filtered",
            "HardwareZone — telco / MVNO discussion threads",
            "Twitter scraper scaffolded (optional)",
        ],
        "Volume",
        [
            "~15,504 cleaned & labeled posts (full corpus)",
            "158 telco-relevant posts (dashboard analysis sample)",
            "300-record blind representative set awaiting human annotation",
            "Brands: Singtel, StarHub, M1, Eight, Giga, SIMBA, Zym, …",
        ],
    )
    add_content_slide(
        prs,
        "Mobile-specific issue taxonomy",
        [
            "Network Quality — signal, coverage, speed, outages and 4G/5G",
            "Pricing & Promotions — prices, discounts, deals and promotion fulfilment",
            "Mobile Plans — SIM-only allowances, terms and plan features",
            "Roaming / Porting — overseas connectivity and number transfer",
            "Customer Service / Billing & Payment — support, charges and refunds",
            "App & Account / Devices — login, apps, phones, SIMs and routers",
            "General Discussion — telco news and opinions without a specific issue",
        ],
        subtitle="Stored as issue_primary on each row in issues_posts_labeled_*.csv",
    )

    add_section_slide(prs, "D.  Sentiment & Issue Methods", "~4 minutes")
    add_table_slide(
        prs,
        "Modelling approach",
        ["Task", "Method", "Output"],
        [
            ["Telco detection", "Regex on thread_title + post_text", "telco_label"],
            ["Sentiment (baseline)", "VADER compound score", "happy / not_happy / neutral"],
            ["Sentiment (optional)", "LLM via --use-llm-sentiment", "llm_sentiment_label"],
            ["Issue extraction", "Keyword rules + optional LLM", "issue_primary"],
            ["Evaluation", "Manual labels on n=150 sample", "sentiment_benchmark.json"],
        ],
    )
    add_content_slide(
        prs,
        "Evaluation & honesty about methods",
        [
            "VADER benchmarked against 150 manually labeled Reddit posts",
            "LLM integration is built in (telco_labeler, issue_extraction) — optional at runtime",
            "Transformer benchmark scaffolded; not yet fully compared on same sample",
            "Dashboard sample uses auto-labels + keyword-inferred issues where manual labels absent",
            "Important: forum tone ≠ national NPS; Reddit more negative than HWZ",
        ],
    )

    add_section_slide(prs, "E.  Results & Dashboard", "~5 minutes")
    add_two_column_slide(
        prs,
        "Sentiment findings (n=158 telco-relevant)",
        "Overall",
        ["61% happy", "22% not_happy", "18% neutral"],
        "By source",
        [
            "Reddit (n=67): 49% happy, 30% negative",
            "HWZ (n=91): 69% happy, 15% negative",
            "HWZ skewed toward Eight launch / plan threads",
        ],
    )
    add_table_slide(
        prs,
        "Issue breakdown (dashboard sample)",
        ["Theme", "Share", "Example signal"],
        [
            ["App & Account", "24%", "Login, verification and self-service app friction"],
            ["Network Quality", "19%", "Dead zones, outages and MVNO priority concerns"],
            ["General Discussion", "15%", "Telco news and opinions without a specific issue"],
            ["Mobile Plans", "12%", "SIM-only allowances and plan comparisons"],
            ["Pricing & Promotions", "8%", "Price-value, discounts and fulfilment"],
            ["Billing & Payment", "8%", "Charges, refunds and payment handling"],
            ["Roaming", "6%", "Malaysia and regional connectivity"],
            ["Devices", "4%", "Phones, SIM/eSIM, routers and equipment"],
            ["Porting", "3%", "Number-transfer and dropdown gaps"],
            ["Customer Service", "1%", "Hotline, agent and escalation experience"],
        ],
    )
    add_table_slide(
        prs,
        "Cross-brand highlights (≥5 mentions)",
        ["Telco", "Mentions", "Neg %", "Dominant themes"],
        [
            ["StarHub", "56", "27%", "Pricing, CS, promo fulfilment"],
            ["M1", "53", "25%", "Coverage, 4G/5G transition"],
            ["Singtel", "51", "16%", "ONR/bridge mode, equipment"],
            ["Eight", "14", "29%", "Launch pricing, tiering, porting"],
            ["Giga", "6", "67%", "Network reliability (small n)"],
        ],
    )
    add_content_slide(
        prs,
        "Dashboard deliverables",
        [
            "dashboard/index.html — static Chart.js report for capstone write-up",
            "  • Sentiment doughnut, source comparison, issue bars, brand mentions",
            "  • Per-telco table, quotes, recommendations, limitations",
            "dashboard/generate_dashboard.py — regenerates HTML from latest CSVs",
            "dashboard/app.py — Streamlit with filters (source / telco / sentiment / date)",
        ],
        subtitle="Regenerate before demo: python dashboard/generate_dashboard.py",
    )
    add_demo_slide(prs)

    add_section_slide(prs, "F.  Limitations & Next Steps", "~2 minutes")
    add_two_column_slide(
        prs,
        "Limitations",
        "Data & method",
        [
            "Forum users ≠ all mobile subscribers",
            "Reddit over-indexes on complaints",
            "HWZ over-indexes on launch threads (Eight)",
            "Small n for Giga, SIMBA, GOMO",
            "Auto-sentiment misses sarcasm / thread context",
        ],
        "Next steps",
        [
            "Transformer sentiment benchmark",
            "Fill issue_manual on evaluation sample",
            "LLM issue extraction on unresolved rows",
            "Scale coverage per telco (coverage_checker)",
            "Final report: dashboard screenshots + recommendations",
        ],
    )
    add_content_slide(
        prs,
        "Key takeaways for industry",
        [
            "Pricing and MVNO value dominate forum conversation",
            "Network quality is hyper-local — same host network, different user experience",
            "Porting and identity-document friction create disproportionate outrage",
            "Bundled roaming is a key decision moment (Malaysia travel threads)",
            "Transparent host-network + MVNO priority disclosure builds trust at launch",
        ],
    )
    add_thankyou_slide(prs)

    prs.save(OUT)
    return OUT


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate SMU-branded capstone walkthrough PPT")
    parser.add_argument(
        "--template",
        type=Path,
        default=None,
        help=f"SMU template .pptx (default: {DEFAULT_TEMPLATE})",
    )
    args = parser.parse_args()
    path = build(args.template)
    print(f"Wrote {path} (SMU template backgrounds)")


if __name__ == "__main__":
    main()
