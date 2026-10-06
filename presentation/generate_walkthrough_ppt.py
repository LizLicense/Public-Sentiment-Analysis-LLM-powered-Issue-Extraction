#!/usr/bin/env python3
"""Generate the capstone walkthrough deck for the professor, on the SMU template.

Usage (from project root):
  python presentation/generate_walkthrough_ppt.py
  python presentation/generate_walkthrough_ppt.py --template "presentation/smu template.pptx"

Every figure on the slides comes from final_report.tex, data/evaluation/ outputs,
or the regenerated dashboard. Speaker notes hold the talk track and Q&A answers.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from pptx import Presentation
except ImportError:  # fall back to the vendored copy
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".pip_packages"))
    from pptx import Presentation

from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

HERE = Path(__file__).resolve().parent
DEFAULT_TEMPLATE = HERE / "smu template.pptx"
OUT = HERE / "capstone_walkthrough.pptx"

# SMU template custom layouts
LAYOUT_BANNER = 11   # 1_Title and Content: 1.49" SMU banner, gold from ~2.8"
LAYOUT_STRIP = 12    # 1_Section Header: 0.75" SMU strip

# Palette sampled from the SMU banner
NAVY = "1C2E6E"
GOLD = "D29B08"
INK = "1E293B"
MUTED = "5B6475"
TINT = "F2F4F9"
GOLD_TINT = "FBF3DF"
LINE = "D5DAE5"
GRAY_BAR = "A3AAB8"
MID_NAVY = "5C6FA6"
WHITE = "FFFFFF"

FONT = "Calibri"
LEFT = 0.6
RIGHT = 12.73
BODY_TOP = 1.8
# Content-slide title box: inside the gold part of the banner (14.2 cm, 1.32 cm; banner ends at 3.78 cm)
TITLE_X, TITLE_Y, TITLE_W, TITLE_H = 14.2 / 2.54, 1.32 / 2.54, 19.0 / 2.54, 2.3 / 2.54


def rgb(hex_code: str) -> RGBColor:
    return RGBColor.from_string(hex_code)


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def resolve_template(path: Path | None) -> Path:
    if path and path.exists():
        return path
    if DEFAULT_TEMPLATE.exists():
        return DEFAULT_TEMPLATE
    raise FileNotFoundError(f"SMU template not found. Tried: {path}, {DEFAULT_TEMPLATE}")


def clear_slides(prs: Presentation) -> None:
    sld_ids = prs.slides._sldIdLst
    for sld_id in list(sld_ids):
        prs.part.drop_rel(sld_id.rId)
        sld_ids.remove(sld_id)


def _bullet(paragraph, indent: float = 0.28, char: str = "•", color: str = GOLD) -> None:
    """Real PowerPoint bullet. Call after spacing is set so child order stays valid."""
    p_pr = paragraph._p.get_or_add_pPr()
    p_pr.set("marL", str(Emu(Inches(indent))))
    p_pr.set("indent", str(-Emu(Inches(indent))))
    bu_clr = p_pr.makeelement(qn("a:buClr"), {})
    srgb = bu_clr.makeelement(qn("a:srgbClr"), {"val": color})
    bu_clr.append(srgb)
    p_pr.append(bu_clr)
    p_pr.append(p_pr.makeelement(qn("a:buFont"), {"typeface": "Arial"}))
    p_pr.append(p_pr.makeelement(qn("a:buChar"), {"char": char}))


def add_text(
    slide,
    x: float,
    y: float,
    w: float,
    h: float,
    paras,
    *,
    size: float = 16,
    color: str = INK,
    bold: bool = False,
    italic: bool = False,
    align=PP_ALIGN.LEFT,
    anchor=MSO_ANCHOR.TOP,
    bullets: bool = False,
    space_after: float = 6,
    line_spacing: float | None = None,
):
    """Add a text box. `paras` is a string or a list of paragraphs; a paragraph is
    a string or a list of (text, overrides) runs."""
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    if isinstance(paras, str):
        paras = [paras]
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(space_after)
        if line_spacing:
            p.line_spacing = line_spacing
        runs = para if isinstance(para, list) else [(para, {})]
        for text, over in runs:
            r = p.add_run()
            r.text = text
            f = r.font
            f.name = FONT
            f.size = Pt(over.get("size", size))
            f.bold = over.get("bold", bold)
            f.italic = over.get("italic", italic)
            f.color.rgb = rgb(over.get("color", color))
        if bullets:
            _bullet(p)
    return box


def add_box(slide, x, y, w, h, fill=TINT, line=None, radius=0.06, shape=MSO_SHAPE.ROUNDED_RECTANGLE):
    shp = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        shp.adjustments[0] = radius
    shp.fill.solid()
    shp.fill.fore_color.rgb = rgb(fill)
    if line:
        shp.line.color.rgb = rgb(line)
        shp.line.width = Pt(1)
    else:
        shp.line.fill.background()
    shp.shadow.inherit = False
    return shp


def shape_label(shp, text, *, size=14, color=WHITE, bold=True, align=PP_ALIGN.CENTER):
    tf = shp.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.08)
    tf.margin_top = tf.margin_bottom = Inches(0.04)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    lines = text.split("\n")
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        r = p.add_run()
        r.text = line
        r.font.name = FONT
        r.font.size = Pt(size if i == 0 else size - 3)
        r.font.bold = bold if i == 0 else False
        r.font.color.rgb = rgb(color)


def add_notes(slide, notes: str) -> None:
    slide.notes_slide.notes_text_frame.text = notes


def page_number(slide, n: int) -> None:
    add_text(slide, 12.2, 7.05, 0.6, 0.3, str(n), size=10, color=MUTED, align=PP_ALIGN.RIGHT)


def style_axis_text(axis, size=12, color=MUTED):
    axis.tick_labels.font.size = Pt(size)
    axis.tick_labels.font.name = FONT
    axis.tick_labels.font.color.rgb = rgb(color)


def bar_chart(
    slide, x, y, w, h, categories, values, colors, *,
    number_format="0.000", maximum=None, horizontal=False, label_size=14, axis_size=12,
):
    data = CategoryChartData()
    data.categories = categories
    data.add_series("Value", values)
    kind = XL_CHART_TYPE.BAR_CLUSTERED if horizontal else XL_CHART_TYPE.COLUMN_CLUSTERED
    chart = slide.shapes.add_chart(kind, Inches(x), Inches(y), Inches(w), Inches(h), data).chart
    chart.has_legend = False
    chart.has_title = False
    plot = chart.plots[0]
    plot.gap_width = 55
    series = plot.series[0]
    for i, color in enumerate(colors):
        point = series.points[i]
        point.format.fill.solid()
        point.format.fill.fore_color.rgb = rgb(color)
    plot.has_data_labels = True
    labels = plot.data_labels
    labels.number_format = number_format
    labels.number_format_is_linked = False
    labels.position = XL_LABEL_POSITION.OUTSIDE_END
    labels.font.size = Pt(label_size)
    labels.font.bold = True
    labels.font.name = FONT
    labels.font.color.rgb = rgb(INK)
    value_axis = chart.value_axis
    value_axis.minimum_scale = 0
    if maximum is not None:
        value_axis.maximum_scale = maximum
    value_axis.has_major_gridlines = not horizontal
    if value_axis.has_major_gridlines:
        value_axis.major_gridlines.format.line.color.rgb = rgb(LINE)
    value_axis.visible = not horizontal
    value_axis.tick_labels.number_format = number_format.replace(".000", ".0")
    value_axis.tick_labels.number_format_is_linked = False
    value_axis.format.line.fill.background()
    style_axis_text(value_axis, axis_size)
    category_axis = chart.category_axis
    category_axis.format.line.color.rgb = rgb(LINE)
    category_axis.has_major_gridlines = False
    style_axis_text(category_axis, axis_size, INK)
    if horizontal:
        category_axis.reverse_order = True
    return chart


def grouped_chart(slide, x, y, w, h, categories, series, *, number_format="0", maximum=None, horizontal=False):
    """series: list of (name, values, color)."""
    data = CategoryChartData()
    data.categories = categories
    for name, values, _ in series:
        data.add_series(name, values)
    kind = XL_CHART_TYPE.BAR_CLUSTERED if horizontal else XL_CHART_TYPE.COLUMN_CLUSTERED
    chart = slide.shapes.add_chart(kind, Inches(x), Inches(y), Inches(w), Inches(h), data).chart
    chart.has_title = False
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.TOP
    chart.legend.include_in_layout = False
    chart.legend.font.size = Pt(12)
    chart.legend.font.name = FONT
    chart.legend.font.color.rgb = rgb(INK)
    plot = chart.plots[0]
    plot.gap_width = 70
    plot.overlap = -10
    for s, (_, _, color) in zip(plot.series, series):
        s.format.fill.solid()
        s.format.fill.fore_color.rgb = rgb(color)
    plot.has_data_labels = True
    labels = plot.data_labels
    labels.number_format = number_format
    labels.number_format_is_linked = False
    labels.position = XL_LABEL_POSITION.OUTSIDE_END
    labels.font.size = Pt(11)
    labels.font.name = FONT
    labels.font.color.rgb = rgb(INK)
    value_axis = chart.value_axis
    value_axis.minimum_scale = 0
    if maximum is not None:
        value_axis.maximum_scale = maximum
    value_axis.visible = False
    value_axis.has_major_gridlines = False
    category_axis = chart.category_axis
    category_axis.format.line.color.rgb = rgb(LINE)
    style_axis_text(category_axis, 12, INK)
    if horizontal:
        category_axis.reverse_order = True
    return chart


def add_table(slide, x, y, w, col_widths, header, rows, *, size=12, row_h=0.42, header_fill=NAVY, highlight_rows=()):
    n_rows = len(rows) + 1
    shape = slide.shapes.add_table(n_rows, len(header), Inches(x), Inches(y), Inches(w), Inches(row_h * n_rows))
    table = shape.table
    for j, cw in enumerate(col_widths):
        table.columns[j].width = Inches(cw)
    for i in range(n_rows):
        table.rows[i].height = Inches(row_h)

    def fill_cell(cell, text, *, bold=False, color=INK, fill=WHITE, align=PP_ALIGN.LEFT):
        cell.fill.solid()
        cell.fill.fore_color.rgb = rgb(fill)
        cell.margin_left = cell.margin_right = Inches(0.1)
        cell.margin_top = cell.margin_bottom = Inches(0.04)
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf = cell.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.alignment = align
        r = p.add_run()
        r.text = text
        r.font.name = FONT
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = rgb(color)

    for j, text in enumerate(header):
        fill_cell(table.cell(0, j), text, bold=True, color=WHITE, fill=header_fill)
    for i, row in enumerate(rows, start=1):
        fill = GOLD_TINT if (i - 1) in highlight_rows else (TINT if i % 2 == 0 else WHITE)
        for j, text in enumerate(row):
            fill_cell(table.cell(i, j), text, fill=fill, bold=(i - 1) in highlight_rows and j == 0)
    return table


# ---------------------------------------------------------------------------
# Slide templates
# ---------------------------------------------------------------------------


class Deck:
    def __init__(self, template: Path):
        self.prs = Presentation(str(template))
        clear_slides(self.prs)
        self.count = 0

    def _new(self, layout: int):
        self.count += 1
        return self.prs.slides.add_slide(self.prs.slide_layouts[layout])

    def content(self, title: str, notes: str):
        slide = self._new(LAYOUT_BANNER)
        size = 24 if len(title) <= 66 else 20  # 24 pt fits two lines of ~45 characters in the box
        add_text(slide, TITLE_X, TITLE_Y, TITLE_W, TITLE_H, title, size=size, bold=True, color=NAVY,
                 anchor=MSO_ANCHOR.MIDDLE, space_after=0, line_spacing=0.95)
        page_number(slide, self.count)
        add_notes(slide, notes)
        return slide

    def section(self, letter: str, title: str, question: str, minutes: str, notes: str):
        slide = self._new(LAYOUT_STRIP)
        badge = add_box(slide, LEFT + 0.3, 2.35, 1.35, 1.35, fill=GOLD, radius=0.12)
        shape_label(badge, letter, size=48)
        add_text(slide, 2.65, 2.2, 9.5, 0.9, title, size=40, bold=True, color=NAVY)
        add_text(slide, 2.65, 3.1, 9.5, 0.6, question, size=20, color=MUTED)
        add_text(slide, 2.65, 3.85, 9.5, 0.4, minutes, size=16, bold=True, color=GOLD)
        page_number(slide, self.count)
        add_notes(slide, notes)
        return slide

    def strip(self, notes: str):
        slide = self._new(LAYOUT_STRIP)
        page_number(slide, self.count)
        add_notes(slide, notes)
        return slide

    def save(self, path: Path) -> Path:
        self.prs.save(path)
        return path


def stat(slide, x, y, w, big, label, *, big_color=NAVY, label_color=MUTED, big_size=40, label_size=14):
    big_h = big_size * 1.2 / 72
    add_text(slide, x, y, w, big_h, big, size=big_size, bold=True, color=big_color)
    add_text(slide, x, y + big_h + 0.05, w, 0.9, label, size=label_size, color=label_color)


def callout(slide, x, y, w, h, heading, body, *, fill=GOLD_TINT, heading_color=NAVY, size=14):
    add_box(slide, x, y, w, h, fill=fill)
    add_text(slide, x + 0.25, y + 0.2, w - 0.5, 0.4, heading, size=size + 2, bold=True, color=heading_color)
    add_text(slide, x + 0.25, y + 0.62, w - 0.5, h - 0.8, body, size=size, color=INK)


def flow(slide, x, y, total_w, h, steps, *, fill=NAVY, text_color=WHITE, size=15, gap=0.08):
    """Chevron process flow. steps: list of 'Title\\nsubtitle'."""
    n = len(steps)
    w = (total_w - gap * (n - 1)) / n
    for i, step in enumerate(steps):
        shape = MSO_SHAPE.PENTAGON if i == 0 else MSO_SHAPE.CHEVRON
        shp = add_box(slide, x + i * (w + gap), y, w, h, fill=fill, shape=shape)
        shp.adjustments[0] = 0.28
        shape_label(shp, step, size=size, color=text_color)


# ---------------------------------------------------------------------------
# The deck
# ---------------------------------------------------------------------------


def build(template_path: Path | None = None) -> Path:
    deck = Deck(resolve_template(template_path))

    # 1 — Title
    s = deck.strip(
        "Good afternoon, Professor. Today I'll walk you through my capstone from the start: the problem, "
        "the data and pipeline, how I evaluated the models, what the data shows, and what I'd recommend.\n\n"
        "One-sentence summary: I built a pipeline that turns Reddit and HardwareZone posts about Singapore "
        "telcos into routed issue queues. My evaluation shows an LLM should label sentiment; for issues, "
        "keyword rules plus a targeted GPT-4o pass win on typical posts but not on hard ones."
    )
    add_text(s, LEFT + 0.3, 1.55, 7.6, 1.9, ["From Forum Posts", "to Telco Actions"], size=44, bold=True,
             color=NAVY, space_after=0)
    add_text(s, LEFT + 0.3, 3.55, 7.4, 1.2,
             "Public sentiment analysis of Singapore mobile-plan discussions with LLM-powered issue extraction",
             size=20, color=MUTED)
    add_text(s, LEFT + 0.3, 5.45, 7.4, 0.9,
             ["Zixin  ·  Capstone project walkthrough",
              "SMU School of Computing and Information Systems  ·  September 2026"],
             size=14, color=INK, space_after=2)
    add_box(s, 8.75, 1.35, 3.95, 5.35, fill=NAVY, radius=0.05)
    for i, (big, label) in enumerate([
        ("9,162", "unique posts in 349 telco threads"),
        ("395", "posts hand-labelled for evaluation"),
        ("0.631", "sentiment macro F1, GPT-4o-mini (VADER 0.360)"),
        ("≈ $6.50", "for all LLM work combined"),
    ]):
        stat(s, 9.1, 1.6 + i * 1.25, 3.4, big, label, big_color=GOLD, label_color=WHITE, big_size=30,
             label_size=13)

    # 2 — Roadmap
    s = deck.content(
        "Roadmap for the next 22 minutes",
        "I've split the talk into five parts. Most of the time goes to evaluation, because that's where "
        "the project's main finding is. I'll show the live dashboard in part D, and I've kept backup "
        "slides with the detailed tables and answers to questions I expect.",
    )
    flow(s, LEFT, 2.1, RIGHT - LEFT, 1.25, [
        "A  Problem\n2 min", "B  Data & pipeline\n4 min", "C  Evaluation\n7 min",
        "D  Findings\n5 min", "E  Actions\n4 min",
    ], size=16)
    callout(s, LEFT, 4.0, RIGHT - LEFT, 1.75, "The claim I'll defend",
            [[("Use an LLM for sentiment. ", {"bold": True}),
              ("For issues, use keyword rules plus a targeted GPT-4o pass, and report honestly where that fails. ", {}),
              ("Put a person in the loop before acting. ", {"bold": True}),
              ("Every number in this deck traces to a file in the repository.", {})]], size=18)

    # 3 — Section A
    deck.section("A", "Problem and research questions", "Why forum posts, and what I set out to answer",
                 "About 2 minutes",
                 "Part A: why this problem matters and the four research questions that shape the rest of the talk.")

    # 4 — Problem + RQs
    s = deck.content(
        "Forums surface pain points before surveys do",
        "Singapore customers talk about plans, coverage, roaming and porting on Reddit and HardwareZone every "
        "day. That's unsolicited feedback an operator doesn't have to pay for, but it's messy: Singlish, "
        "sarcasm, quoted replies, several brands in one post.\n\n"
        "I framed the goal as an early-warning screen. It tells a team what to look at this week. It is not "
        "a satisfaction score or NPS, and I'm careful about that throughout. These four research questions "
        "structure the evaluation and findings.",
    )
    add_text(s, LEFT, BODY_TOP + 0.1, 5.4, 4.6, [
        "Customers discuss plans, coverage, roaming and porting in public, unprompted",
        "The text is hard: Singlish, sarcasm, quoted replies, several brands in one post",
        "Brand names collide with ordinary words: “Eight”, “M1”, “Giga”",
        "Goal: an early-warning screen that routes issues to owners, not a CSAT or NPS score",
    ], size=17, bullets=True, space_after=14)
    rqs = [
        ("RQ1", "Which sentiment and issue themes appear most often?"),
        ("RQ2", "How do Reddit and HWZ, and the brands, differ?"),
        ("RQ3", "What does an LLM add over VADER and keyword rules?"),
        ("RQ4", "How can the signals drive operator decisions?"),
    ]
    for i, (tag, text) in enumerate(rqs):
        y = BODY_TOP + 0.1 + i * 1.2
        add_box(s, 6.5, y, 6.23, 1.02, fill=TINT)
        add_text(s, 6.75, y, 0.9, 1.02, tag, size=20, bold=True, color=GOLD, anchor=MSO_ANCHOR.MIDDLE)
        add_text(s, 7.65, y, 4.9, 1.02, text, size=16, color=INK, anchor=MSO_ANCHOR.MIDDLE)

    # 5 — Section B
    deck.section("B", "Data and pipeline", "What I collected and how it flows", "About 4 minutes",
                 "Part B: the data sources, the six pipeline stages, and two data problems I had to solve.")

    # 6 — Pipeline
    s = deck.content(
        "One reproducible pipeline in six stages",
        "Here's the whole system. Scrapers pull Reddit through its public JSON interface and HardwareZone "
        "threads from its XenForo forums. Preprocessing maps both into one schema. The telco labeler detects "
        "brands and scores sentiment with VADER. Issue extraction applies ten keyword-rule labels, then GPT-4o "
        "on the posts the rules couldn't place. The evaluation script scores every method against blind "
        "human labels, and the dashboard generator writes a static HTML report.\n\n"
        "Each stage writes a CSV to data/processed, so I can trace any number in the report back to a file.",
    )
    flow(s, LEFT, 2.0, RIGHT - LEFT, 1.3, [
        "Scrape", "Clean", "Label", "Issues", "Evaluate", "Dashboard",
    ], size=16)
    details = [
        ("scrapers/", "Reddit JSON API, HWZ XenForo threads"),
        ("preprocess.py", "One schema, drop empty and short posts"),
        ("telco_labeler.py", "Brand regex with context, VADER score"),
        ("issue_extraction.py", "10 keyword labels, then GPT-4o on leftovers"),
        ("llm_evaluation.py", "VADER, rules, GPT-4o-mini, GPT-4o vs humans"),
        ("generate_dashboard.py", "Static Chart.js HTML, no server"),
    ]
    col_w = (RIGHT - LEFT - 0.08 * 5) / 6
    for i, (script, what) in enumerate(details):
        x = LEFT + i * (col_w + 0.08)
        add_text(s, x + 0.05, 3.55, col_w - 0.1, 0.5, script, size=12, bold=True, color=NAVY)
        add_text(s, x + 0.05, 4.0, col_w - 0.1, 1.3, what, size=14, color=INK)
    add_box(s, LEFT, 5.55, RIGHT - LEFT, 0.95, fill=GOLD_TINT)
    add_text(s, LEFT + 0.25, 5.55, RIGHT - LEFT - 0.5, 0.95,
             "Every stage writes a CSV to data/processed/, so every number in the report traces to a file.",
             size=16, color=INK, anchor=MSO_ANCHOR.MIDDLE)

    # 7 — Data at a glance
    s = deck.content(
        "9,162 unique posts in 349 telco threads",
        "The raw scrapes looked large: 24,690 rows. But they held only 11,643 unique posts, because the "
        "scrapers saved the same comments again on repeated runs. I removed duplicates by post ID, then "
        "dropped 96 off-topic threads, such as cost-of-living threads where nobody names a telco. That "
        "leaves 9,162 posts in 349 threads: 5,711 from Reddit and 3,451 from HardwareZone.\n\n"
        "Recent Reddit posts and replies come from the Arctic Shift research archive, because Reddit now "
        "blocks unauthenticated access. Only 12% of posts sit in outage threads, so the corpus is mostly "
        "ordinary discussion of plans, coverage and prices.",
    )
    for i, (big, label) in enumerate([
        ("24,690", "raw rows scraped"),
        ("11,643", "unique posts after removing repeat copies"),
        ("9,162", "posts in 349 telco threads"),
        ("12%", "in outage threads"),
    ]):
        x = LEFT + i * 3.1
        add_box(s, x, BODY_TOP + 0.2, 2.85, 2.2, fill=GOLD_TINT if i == 2 else TINT)
        stat(s, x + 0.25, BODY_TOP + 0.45, 2.4, big, label, big_size=38, label_size=15)
    callout(s, LEFT, 4.55, RIGHT - LEFT, 1.85, "Why it matters",
            "Raw row counts overstate the data more than twofold. Every share in this deck is per unique "
            "post, and checked again with every thread weighted equally.", size=16)

    # 8 — Eight problem
    s = deck.content(
        "“Eight” is a telco and a number",
        "One problem that looks trivial but wasn't: Eight is a telco brand and an ordinary word. A naive "
        "match turned 'I took eight buses' into an Eight Telecom mention. So is_eight_telco_reference() "
        "first blocks number phrases like 'eight buses' or 'eight people', then accepts strong patterns like "
        "'Eight Telecom', and otherwise needs telco context within 60 characters. Posts that fail are marked "
        "not telco-relevant, and get no sentiment or issue label, instead of polluting the brand chart.",
    )
    for x, heading, fill, items in [
        (LEFT, "Rejected as a brand", TINT, ["“took eight buses to get home”", "“eight people in my team”",
                                            "“eight years with the same phone”"]),
        (6.8, "Accepted as Eight Telecom", GOLD_TINT, ["“Eight Telecom’s new SIM-only plan”",
                                                       "“ported to eight, it runs on StarHub’s network”",
                                                       "“eight.sg promo for 5G”"]),
    ]:
        add_box(s, x, BODY_TOP + 0.1, 5.93, 2.75, fill=fill)
        add_text(s, x + 0.3, BODY_TOP + 0.3, 5.3, 0.45, heading, size=18, bold=True, color=NAVY)
        add_text(s, x + 0.3, BODY_TOP + 0.9, 5.3, 1.9, items, size=16, color=INK, bullets=True, space_after=8)
    add_text(s, LEFT, 4.95, RIGHT - LEFT, 1.6, [
        [("How it works: ", {"bold": True, "color": NAVY}),
         ("block number phrases first, accept strong patterns (“Eight Telecom”, “eight.sg”), otherwise require "
          "a telco word within 60 characters. Failed matches are marked not telco-relevant and get no "
          "sentiment or issue label.", {})],
    ], size=16)

    # 9 — Taxonomy, with a real example per label
    s = deck.content(
        "Ten issue labels, each mapped to an owner",
        "I designed the taxonomy around who would act on it. Each label maps to a team, so a spike becomes "
        "a routed task rather than a chart. Every quote here is a real post that I labelled in the blind gold "
        "sets, trimmed only where marked. The percentage is the share of the 9,162 posts with that label as "
        "their main issue, so the ten add to 100; a post can still carry several labels. Network is two in "
        "five posts; the next slide explains why I kept labels as small as Porting at 3%.",
    )
    labels = [
        ("Network Quality", "Network team", "41%",
         "“Connection go from 5G to zero then back up multiple times a day.”"),
        ("Pricing & Promotions", "Commercial", "8%",
         "“$60 is yours even if you use $7? I’ll go zero1.”"),
        ("Mobile Plans", "Product", "14%",
         "“My Star Plan got renewed on Nov 3 and I got only 50GB for local data.”"),
        ("Roaming", "Roaming product", "4%",
         "“Tried it in KL to Ipoh no problem. Tested in Hokkaido lately, very nice.”"),
        ("Porting", "MNP operations", "3%",
         "“Probably too many people porting out of m1.”"),
        ("Customer Service", "Service operations", "4%",
         "“Tried. U know that they say? Backend team will update u”"),
        ("Billing & Payment", "Billing", "3%",
         "“…you cannot have any outstanding bill in M1 or they will reject the letter.”"),
        ("App & Account", "Digital CX", "4%",
         "“pretty sure you can only use the ai in the giga app which kinda sucks”"),
        ("Devices", "Device support", "6%",
         "“Anything but Singtel. Singtel are the only one known to use ONR.”"),
        ("General Discussion", "Analyst review", "15%",
         "“…KKR and Singtel will own stakes of 75 per cent and 25 per cent, respectively”"),
    ]
    card_w, card_h = (RIGHT - LEFT - 0.2 * 4) / 5, 2.05
    for i, (label, owner, share, quote) in enumerate(labels):
        col, row = i % 5, i // 5
        x, y = LEFT + col * (card_w + 0.2), BODY_TOP + 0.1 + row * (card_h + 0.2)
        add_box(s, x, y, card_w, card_h, fill=GOLD_TINT if label == "General Discussion" else TINT)
        add_text(s, x + 0.18, y + 0.15, card_w - 0.85, 0.5, label, size=15, bold=True, color=NAVY,
                 space_after=0, line_spacing=0.9)
        add_text(s, x + card_w - 0.68, y + 0.15, 0.5, 0.3, share, size=15, bold=True, color=GOLD,
                 align=PP_ALIGN.RIGHT)
        add_text(s, x + 0.18, y + 0.72, card_w - 0.36, 0.25, owner, size=12, color=MUTED)
        add_text(s, x + 0.18, y + 1.05, card_w - 0.36, 0.9, quote, size=12, italic=True, color=INK, space_after=0)
    add_text(s, LEFT, 6.42, RIGHT - LEFT, 0.5,
             "Gold figure = share of the 9,162 posts with this as the main issue. Quotes are real posts from my blind gold sets. "
             "Issues are multi-label; sentiment is one label per post.", size=12, color=MUTED)

    # 10 — Why these labels
    s = deck.content(
        "I split labels wherever a different team fixes it",
        "The rule behind the taxonomy: if two problems are fixed by different teams, they get different "
        "labels. My first draft used coarser labels, and you can still see them in the representative gold "
        "set: Mobile Plans & Pricing, Customer Service & Account, Network Outage & Connectivity. The scorer "
        "maps those old names onto the new ones. I split them because a price rise goes to Commercial while "
        "a plan allowance goes to Product, and a hotline complaint goes to service operations while a login "
        "failure goes to the digital team. Small labels stay when they are sharp: Customer Service is only "
        "4% of posts but the angriest label at 59% not happy. General Discussion is deliberately a residual, "
        "which is what made the hybrid possible: GPT-4o re-reads only those posts. The honest cost is the "
        "bottom line: finer labels are harder for humans to agree on.",
    )
    add_text(s, LEFT, BODY_TOP + 0.1, 6.0, 0.4, "How my draft labels changed", size=18, bold=True, color=NAVY)
    splits = [
        ("Mobile Plans & Pricing", "Mobile Plans  +  Pricing & Promotions\nProduct  /  Commercial"),
        ("Customer Service & Account", "Customer Service  +  App & Account\nService operations  /  Digital CX"),
        ("Network Outage & Connectivity", "Network Quality\nAlso slow speeds and dead spots, not only outages"),
    ]
    for i, (draft, final) in enumerate(splits):
        y = BODY_TOP + 0.7 + i * 1.2
        shape_label(add_box(s, LEFT, y, 2.3, 1.0, fill=GOLD_TINT), draft, size=14, color=NAVY)
        add_text(s, LEFT + 2.3, y, 0.5, 1.0, "→", size=24, bold=True, color=GOLD,
                 align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        shape_label(add_box(s, LEFT + 2.8, y, 3.4, 1.0, fill=TINT), final, size=14, color=NAVY)
    reasons = [
        ("Small labels stay when the pain is sharp",
         "Customer Service is 4% of posts but the most negative label (59% not happy). Roaming and "
         "Porting each have their own team; merging them would bury their spikes."),
        ("General Discussion is the residual",
         "Used only when nothing specific fits, never beside a label (15% of posts). That makes it the "
         "queue the hybrid sends to GPT-4o."),
        ("Many issues per post, one sentiment",
         "One post can raise roaming and billing at once, so issues are multi-label; sentiment stays one "
         "label per post."),
    ]
    for i, (heading, body) in enumerate(reasons):
        y = BODY_TOP + 0.1 + i * 1.4
        add_text(s, 7.1, y, RIGHT - 7.1, 0.35, heading, size=16, bold=True, color=NAVY)
        add_text(s, 7.1, y + 0.4, RIGHT - 7.1, 0.9, body, size=14, color=INK)
    add_text(s, LEFT, 6.3, RIGHT - LEFT, 0.6, [
        [("The cost of finer labels: ", {"bold": True, "color": NAVY}),
         ("two humans agreed on Network (κ 0.79) but not on Devices (0.16), App & Account (0.17) or "
          "Customer Service (0.28).", {})],
    ], size=14, color=INK)

    # 10 — Section C
    deck.section("C", "Evaluation", "Which method should label what?", "About 7 minutes",
                 "Part C is the core of the project: how I built trustworthy gold labels and what they say about "
                 "VADER, keyword rules, GPT-4o-mini and GPT-4o.")

    # 11 — Evaluation design
    s = deck.content(
        "Blind gold sets: I labelled without seeing any model",
        "The annotation package hides every model column, so my labels can't lean on VADER or the LLMs. Threads are split so the representative and challenge "
        "sets never share a thread, with at most five comments per thread. I labelled 300 representative "
        "posts (295 telco-relevant, used for headline metrics) and 100 challenge posts chosen for sarcasm, "
        "Singlish, mixed brands and long text. Challenge results are reported separately, never pooled. A "
        "second annotator has since labelled 100 overlap posts.",
    )
    for i, (big, label) in enumerate([
        ("300", "representative posts, 295 telco-relevant: headline metrics"),
        ("100", "challenge posts: sarcasm, Singlish, mixed brands, long text"),
        ("100", "second-annotator overlap: 60 representative + 40 challenge"),
    ]):
        y = BODY_TOP + 0.05 + i * 1.6
        add_box(s, LEFT, y, 6.1, 1.42, fill=TINT)
        add_text(s, LEFT + 0.25, y, 1.4, 1.42, big, size=34, bold=True, color=NAVY, anchor=MSO_ANCHOR.MIDDLE)
        add_text(s, LEFT + 1.75, y, 4.15, 1.42, label, size=15, color=INK, anchor=MSO_ANCHOR.MIDDLE)
    callout(s, 7.0, BODY_TOP + 0.05, 5.73, 4.62, "What keeps it blind and fair",
            ["The sheets hide every model label and score, so no answer can be copied.",
             "Representative and challenge sets never share a thread, and each thread gives at most five "
             "comments.",
             "Challenge results are reported separately, never pooled with the headline set."],
            size=16)

    # 12 — Sentiment results
    s = deck.content(
        "GPT-4o-mini labels sentiment far better than VADER",
        "On the 295 representative posts, VADER's macro F1 is 0.360; GPT-4o-mini reaches 0.631. The "
        "clearest failure: of 147 posts I labelled not happy, VADER called 61 of them happy. Its lexicon "
        "sees words like 'better' and '$12' and misses that the person just switched away.\n\n"
        "I bootstrapped the difference: mini beats VADER by 0.27, 95% interval 0.19 to 0.35, so this is not "
        "noise. GPT-4o is statistically tied with mini (interval −0.04 to +0.06) at about 17 times the cost, "
        "so mini is the right choice for sentiment. It also holds on the hard challenge posts: mini 0.773, "
        "GPT-4o 0.712, VADER 0.491. And a second mini run reproduced 292 of 295 labels, so it's stable.",
    )
    bar_chart(s, LEFT, BODY_TOP, 6.6, 4.8, ["VADER", "GPT-4o-mini", "GPT-4o"], [0.360, 0.631, 0.623],
              [GRAY_BAR, GOLD, MID_NAVY], maximum=0.8)
    add_text(s, LEFT, 6.62, 6.6, 0.35, "Sentiment macro F1, representative set (n = 295)", size=12, color=MUTED)
    stat(s, 7.7, BODY_TOP + 0.1, 5.0, "61 of 147", "posts I labelled not happy that VADER called happy",
         big_color=NAVY, big_size=36, label_size=15)
    add_text(s, 7.7, 3.75, 5.0, 3.0, [
        [("+0.27 ", {"bold": True, "color": NAVY}), ("macro F1 for mini over VADER (95% CI +0.19 to +0.35)", {})],
        [("Tie ", {"bold": True, "color": NAVY}), ("between mini and GPT-4o (95% CI −0.05 to +0.06)", {})],
        [("~17× ", {"bold": True, "color": NAVY}), ("GPT-4o’s cost over mini for the same run", {})],
    ], size=16, bullets=True, space_after=12)

    # 13 — Issue results
    s = deck.content(
        "For issues, rules first and GPT-4o only on the leftovers",
        "Issues surprised me. Keyword rules score 0.639 macro F1. Running GPT-4o-mini on every post scores "
        "only 0.504, and GPT-4o 0.600, which is statistically a tie with rules. The LLMs are precise but "
        "incomplete: they return one or two topics when the post has several.\n\n"
        "So I built a hybrid. Rules label everything; the 98 gold posts that rules left as General "
        "Discussion go to GPT-4o, which reassigned 70 of them. That scores 0.680, the only method that beats "
        "rules on this set, with a bootstrap interval of +0.011 to +0.072. But I designed it after seeing "
        "these results, so the next slide tests it on posts it wasn't designed on.",
    )
    bar_chart(s, LEFT, BODY_TOP, 7.0, 4.8, ["Keyword rules", "GPT-4o-mini\nall posts", "GPT-4o\nall posts",
                                            "Hybrid"], [0.639, 0.504, 0.600, 0.680],
              [MID_NAVY, GRAY_BAR, GRAY_BAR, GOLD], maximum=0.8)
    add_text(s, LEFT, 6.62, 7.0, 0.35, "Issue macro F1, multi-label, representative set (n = 295)", size=12,
             color=MUTED)
    steps = [("1", "Rules label every post"), ("2", "98 of 295 left as General Discussion"),
             ("3", "GPT-4o relabels those 98, moves 70")]
    for i, (num, text) in enumerate(steps):
        y = BODY_TOP + 0.1 + i * 0.95
        badge = add_box(s, 8.0, y, 0.6, 0.6, fill=NAVY, shape=MSO_SHAPE.OVAL)
        shape_label(badge, num, size=16)
        add_text(s, 8.8, y, 3.9, 0.6, text, size=16, color=INK, anchor=MSO_ANCHOR.MIDDLE)
    callout(s, 8.0, 4.8, 4.73, 1.75, "Gain over rules: +0.041",
            "95% CI +0.011 to +0.072. Chosen on this set, so it needs a held-out test.", size=14)

    # 13b — Held-out test
    s = deck.content(
        "The hybrid didn’t survive the held-out test",
        "This is the result I'm most careful about. On the 100 challenge posts, which the hybrid never saw, "
        "its gain over rules shrinks to 0.01, well inside the noise: the interval is −0.04 to +0.07. GPT-4o "
        "labelling every post wins there instead, 0.596, beating both rules and the hybrid with intervals "
        "clear of zero. It does better on customer service, roaming and billing, while rules still catch "
        "more device posts.\n\n"
        "So the honest reading is split. On typical posts, which is what the corpus looks like, the hybrid "
        "is best, but its 0.680 is optimistic. On hard posts, GPT-4o on every post is best. Sentiment, by "
        "contrast, held up on both sets.",
    )
    grouped_chart(s, LEFT, BODY_TOP - 0.05, 7.4, 4.9, ["Keyword rules", "GPT-4o all posts", "Hybrid"],
                  [("Representative (n = 295)", [0.639, 0.600, 0.680], GRAY_BAR),
                   ("Challenge, held out (n = 100)", [0.499, 0.596, 0.509], NAVY)],
                  number_format="0.000", maximum=0.8)
    add_text(s, LEFT, 6.62, 7.4, 0.35, "Issue macro F1 against human labels", size=12, color=MUTED)
    add_table(s, 8.3, BODY_TOP + 0.05, 4.43, [2.55, 1.88], ["Challenge set", "95% CI"], [
        ["Hybrid − rules", "−0.04 to +0.07"],
        ["GPT-4o − rules", "+0.01 to +0.18"],
        ["GPT-4o − hybrid", "+0.02 to +0.15"],
    ], size=14, row_h=0.5, highlight_rows=(1, 2))
    callout(s, 8.3, 4.2, 4.43, 2.35, "What I conclude",
            "Keep the hybrid for typical posts, but report 0.680 as optimistic. On hard posts, GPT-4o on "
            "every post is worth its cost.", size=14)

    # 13c — Recent-posts gold check
    s = deck.content(
        "The sentiment result holds on recent posts",
        "My representative and challenge gold sets were drawn from posts up to early April. So I labelled a "
        "third blind set of 100 posts from April to September, 97 of them telco-relevant, and scored the "
        "labels already in the corpus against it. No new API calls.\n\n"
        "Sentiment carries over: GPT-4o-mini 0.637 against VADER 0.428, the same as on the representative "
        "set, on both Reddit and HWZ. But the error has a direction: of 39 posts I called not happy, mini called 15 neutral. So the "
        "corpus not-happy share is probably an underestimate. Issues are harder on recent posts for every method; the "
        "hybrid still beats rules, but only reaches 0.477.",
    )
    bar_chart(s, LEFT, BODY_TOP, 7.4, 4.8,
              ["Sentiment\nVADER", "Sentiment\nGPT-4o-mini", "Issues\nrules", "Issues\nGPT-4o-mini", "Issues\nhybrid"],
              [0.428, 0.637, 0.413, 0.440, 0.477], [GRAY_BAR, GOLD, GRAY_BAR, GRAY_BAR, NAVY], maximum=0.8)
    add_text(s, LEFT, 6.62, 7.4, 0.35, "Macro F1 on 97 recent gold posts (Apr–Sep 2026), production labels", size=12, color=MUTED)
    add_table(s, 8.3, BODY_TOP + 0.05, 4.43, [2.63, 0.9, 0.9], ["Share of posts", "Human", "Mini"], [
        ["Happy", "30%", "26%"], ["Not happy", "40%", "33%"], ["Neutral", "30%", "41%"],
    ], size=14, row_h=0.5, highlight_rows=(1, 2))
    callout(s, 8.3, 4.2, 4.43, 2.35, "What it means",
            "Mini reads complaints as neutral, so the corpus not-happy share is likely understated, not "
            "inflated.", size=14)

    # 14 — Devices
    s = deck.content(
        "LLMs miss the equipment jargon that rules catch",
        "Why do all-row LLMs lose on issues? Devices is the clearest case. Rules recall 81% of device posts; "
        "GPT-4o recalls 25% and GPT-4o-mini 6%. Posts like 'Starhub, no ONR, no CGNAT' are pure equipment "
        "jargon: an optical network router and carrier-grade NAT. The rules have those terms; the LLM reads "
        "the post as general chat, and mini even flips its sentiment to happy.\n\n"
        "This is why the hybrid keeps rule hits and only uses the LLM where rules have nothing. The gap "
        "holds on the challenge set too: rules 75%, GPT-4o 33%.",
    )
    bar_chart(s, LEFT, BODY_TOP, 6.6, 3.3, ["Keyword rules", "GPT-4o", "GPT-4o-mini"], [0.81, 0.25, 0.06],
              [MID_NAVY, GRAY_BAR, GRAY_BAR], number_format="0%", maximum=1.0, horizontal=True,
              label_size=16, axis_size=14)
    add_text(s, LEFT, 5.15, 6.6, 0.35, "Devices recall, representative set (52 device posts)", size=12,
             color=MUTED)
    add_text(s, LEFT, 5.6, 6.6, 1.0,
             "All-row LLMs return one or two topics when a post has several. On the challenge set rules "
             "still recall 75% of device posts vs GPT-4o’s 33%.", size=15, color=INK)
    add_box(s, 7.6, BODY_TOP + 0.1, 5.13, 4.6, fill=GOLD_TINT)
    add_text(s, 7.9, BODY_TOP + 0.35, 4.6, 0.9, "“Starhub, no ONR, no CGNAT”", size=24, bold=True, color=NAVY,
             italic=True)
    add_table(s, 7.9, 3.2, 4.55, [2.35, 2.2], ["Labeller", "Issue label"], [
        ["Human", "Devices"], ["Keyword rules", "Devices"], ["GPT-4o-mini", "General Discussion"],
    ], size=14, row_h=0.46, highlight_rows=(2,))
    add_text(s, 7.9, 5.25, 4.6, 1.0, "ONR = optical network router; CGNAT = carrier-grade NAT. Mini also "
             "flipped this post’s sentiment to happy.", size=13, color=MUTED)

    # 15 — Examples
    s = deck.content(
        "Four posts that show where VADER breaks",
        "Four real examples, paraphrased. A short status update like 'eSIM still down' has no sentiment "
        "words, so VADER says neutral. A switching story with 'better' and 'just $12' reads as happy to "
        "VADER, but it's a complaint about 5G drops. Elongated slang is outside the lexicon. And a user ready "
        "to port out after an outage is unhappy, whatever words they use. The LLM gets all four right.",
    )
    add_table(s, LEFT, BODY_TOP + 0.1, RIGHT - LEFT, [1.35, 5.4, 1.85, 1.75, 1.78],
              ["Post", "What it says (paraphrased)", "Human", "VADER", "GPT-4o-mini"], [
                  ["REP-0003", "“SingTel eSIM still down”", "not happy", "neutral", "not happy"],
                  ["REP-0014", "Switched after 5G drops, “better… just $12”", "not happy", "happy", "not happy"],
                  ["CHL-0005", "“Smoooooooth as baby butttttt”", "happy", "neutral", "happy"],
                  ["CHL-0029", "Nationwide outage, ready to port out", "not happy", "happy", "not happy"],
              ], size=17, row_h=0.8)
    add_text(s, LEFT, 6.0, RIGHT - LEFT, 0.8,
             "Short status updates, price words and stretched slang fool a lexicon. Switching intent is a "
             "complaint, not praise.", size=16, color=INK)

    # 16 — Cost
    s = deck.content(
        "All the LLM work cost about $6.50",
        "Cost was a design constraint. Evaluating mini on 295 posts cost under one cent; GPT-4o on the same "
        "posts cost 15 cents. The biggest job sent 12,497 unresolved rows to GPT-4o: about 41 minutes, zero "
        "failed batches, $4.80. Sentiment on all 9,162 posts cost 28 cents. The finished jobs total about "
        "$5.30; a first pass I discarded, because it sent Reddit posts without their thread titles, added "
        "about $1.15. VADER and the rules label the "
        "same posts in a fraction of a second for free.",
    )
    stat(s, LEFT, BODY_TOP + 0.1, 3.6, "$0.28", "GPT-4o-mini sentiment on all 9,162 posts", big_size=50,
         label_size=15)
    add_table(s, 4.6, BODY_TOP + 0.05, 8.13, [2.9, 1.6, 1.0, 1.1, 1.53],
              ["Job", "Model", "Posts", "Seconds", "Est. USD"], [
                  ["Representative eval", "GPT-4o-mini", "295", "74", "0.0087"],
                  ["Representative eval", "GPT-4o", "295", "73", "0.145"],
                  ["Challenge eval", "GPT-4o-mini", "100", "28", "0.0030"],
                  ["Challenge eval", "GPT-4o", "100", "20", "0.050"],
                  ["Unresolved issue rows", "GPT-4o", "12,497", "2,445", "4.80"],
                  ["All-post sentiment", "GPT-4o-mini", "9,162", "—", "0.28"],
              ], size=13, row_h=0.44, highlight_rows=(4, 5))
    add_text(s, 4.6, 5.75, 8.13, 0.8,
             "Per post: GPT-4o ≈ $0.0005, GPT-4o-mini ≈ $0.00003. VADER and rules: free, under 0.3 s.",
             size=15, color=INK)

    # 17 — Section D
    deck.section("D", "Findings", "What the labelled data says", "About 5 minutes",
                 "Part D: what GPT-4o-mini sentiment and the hybrid issue labels show on the 9,162-post "
                 "corpus, the March outage as a case study, then a short dashboard demo.")

    # 18 — Corpus shift
    s = deck.content(
        "GPT-4o moved 1,887 posts out of General Discussion",
        "Rules alone left 3,229 of the 9,162 posts, 35%, in General Discussion. After GPT-4o relabelled them, "
        "that dropped to 1,342, or 15%. Most of the reassigned posts became Network Quality, which gained "
        "995. Devices barely moved, which matches the gold result: rules already catch device posts.\n\n"
        "These corpus reassignments have no human check yet. Before they drive an alert, I'd sample them.",
    )
    grouped_chart(s, LEFT, BODY_TOP - 0.05, 8.2, 5.05,
                  ["General\nDiscussion", "Network\nQuality", "Devices", "Mobile\nPlans", "Pricing &\nPromotions",
                   "Customer\nService"],
                  [("Keyword rules", [3229, 2769, 1611, 2079, 901, 579], GRAY_BAR),
                   ("Rules + GPT-4o hybrid", [1342, 3764, 1691, 2376, 1144, 748], GOLD)],
                  number_format="#,##0", maximum=4000)
    callout(s, 9.1, BODY_TOP + 0.2, 3.63, 4.6, "Read with care",
            ["35% of posts had no rule match.",
             "Most reassigned posts became Network Quality (+995).",
             "No human has checked these 1,887 moves yet."], size=15)

    # 19 — Sentiment on the corpus
    s = deck.content(
        "Two in five posts are not happy, and VADER hides it",
        "On the full corpus, GPT-4o-mini labels 44% of posts not happy and 19% happy. With every thread "
        "weighted equally it's 42%, and outside outage threads 40%, so this holds across weightings. VADER "
        "on the same posts says the opposite: 46% happy. Of the 4,180 posts VADER calls happy, mini reads "
        "1,480 as not happy.\n\n"
        "Neutral is higher than in my gold set, 37% against 32%. The recent-posts gold set explains it: on "
        "April–September posts mini reads some complaints as neutral, so if anything the true not-happy share is higher.",
    )
    grouped_chart(s, LEFT, BODY_TOP - 0.05, 7.6, 4.8, ["Happy", "Not happy", "Neutral"],
                  [("VADER, all posts", [46, 28, 27], GRAY_BAR),
                   ("GPT-4o-mini, all posts", [19, 44, 37], GOLD),
                   ("Human labels, gold set", [18, 50, 32], NAVY)],
                  number_format='0"%"', maximum=70)
    add_text(s, LEFT, 6.62, 7.6, 0.35, "Shares in %; corpus n = 9,162, gold n = 295 (representative set)", size=12, color=MUTED)
    stat(s, 8.6, BODY_TOP + 0.1, 4.1, "44% → 42% → 40%", "not happy: per post, per thread, outside outages",
         big_size=30, label_size=15)
    callout(s, 8.6, 4.0, 4.13, 2.55, "VADER reverses it",
            "Of 4,180 posts VADER calls happy, GPT-4o-mini reads 1,480 as not happy and 1,538 as neutral.",
            size=15)

    # 20 — Issues, platforms and brands
    s = deck.content(
        "Network leads; platforms and brands differ less than they seem",
        "Network quality is still first, 37 to 41% of posts and 46% of the not-happy discussion. Mobile plans "
        "are second and pricing third. App and account is small per post but spread across 115 threads.\n\n"
        "Reddit is 48% not happy against HWZ 37% per post, 42 against 37 outside outages. The rest is topic: "
        "HWZ is mostly plan megathreads. Brands outside outages sit within three points, 40 to 43%, except "
        "Eight, the least negative at 35% under every weighting. So no league table.",
    )
    add_table(s, LEFT, BODY_TOP + 0.05, 7.5, [1.9, 1.3, 1.9, 2.4], ["Not happy", "Posts", "All threads",
                                                                    "Outside outage threads"], [
        ["Reddit", "5,711", "48%", "42%"],
        ["HWZ", "3,451", "37%", "37%"],
        ["Singtel", "3,970", "48%", "42%"],
        ["StarHub", "1,638", "44%", "40%"],
        ["SIMBA", "1,461", "44%", "43%"],
        ["M1", "1,415", "40%", "40%"],
        ["Eight", "734", "35%", "35%"],
    ], size=14, row_h=0.56, highlight_rows=(6,))
    add_text(s, LEFT, 6.4, 7.5, 0.4, "Brands ranked only with ≥92 posts and ≥10 threads; human gold: Reddit 51%, HWZ 47%",
             size=12, color=MUTED)
    callout(s, 8.5, BODY_TOP + 0.05, 4.23, 4.5, "Top issues (share of posts)",
            ["Network Quality 41%",
             "Mobile Plans 14%",
             "Pricing & Promotions 8%",
             "App & Account 4%, in 115 threads"], size=15)

    # 20b — Outage case study
    s = deck.content(
        "Case study: one outage distorted every number",
        "Outage threads, led by the 16 March Singtel mobile outage, fill 45 threads and 1,102 posts, 12% of "
        "the corpus. Inside them 71% of posts are not happy, against 40% everywhere else. And 1,099 of those "
        "1,102 posts are on Reddit.\n\n"
        "So one event creates most of the Reddit–HWZ gap and much of Singtel's lead. Remove the outage threads "
        "and Reddit falls from 48% to 42% not happy, and Singtel from 48% to 42%, next to StarHub at 40%. "
        "That's why every finding in this deck is checked with and without them.",
    )
    add_table(s, LEFT, BODY_TOP + 0.05, 7.6, [3.0, 2.3, 2.3], ["", "Outage threads", "All other threads"], [
        ["Posts", "1,102", "8,060"],
        ["Not happy", "71%", "40%"],
        ["Singtel not happy", "73%", "42%"],
        ["StarHub not happy", "68%", "40%"],
        ["Share on Reddit", "99.7%", "57%"],
    ], size=15, row_h=0.62, highlight_rows=(1, 4))
    callout(s, 8.6, BODY_TOP + 0.05, 4.13, 4.5, "The lesson",
            ["A single incident can create a brand gap and a platform gap.",
             "1,099 of 1,102 outage posts are on Reddit.",
             "Check every finding with the incident removed."], size=15)

    # 21 — Dashboard + huddle
    s = deck.content(
        "The dashboard runs a weekly 30-minute huddle",
        "The dashboard is built around one meeting. Step one, the queue: not-happy posts in Network Quality, "
        "App & Account or Porting, but only act when the week is unusual. Step two, open ten source posts and "
        "drop sarcasm and mislabels. Step three, match what's left to tickets or outages. Step four, one owner "
        "and a date. Step five, next week, check whether that issue's share fell.\n\n"
        "A fixed threshold of 20 posts fired almost every week once I had more data, so the threshold is now "
        "twice the median week, 115 posts. Only two weeks qualify: the March Singtel outage, 352 posts, and "
        "14 September, 149 posts, a multi-brand week with StarHub broadband down and SIMBA app OTP failures. "
        "That's the alert working.\n\n"
        "[Demo] Open dashboard/index.html. Walk through: executive summary, the weekly queue chart, the tone "
        "chart next to VADER and human labels, issue shares per post and per thread, and the recommendations.",
    )
    flow(s, LEFT, 2.0, RIGHT - LEFT, 1.3, [
        "1  Queue", "2  Open 10", "3  Match", "4  One owner", "5  Next week",
    ], size=17)
    step_text = [
        "Not-happy posts in Network, App & Account, Porting; act only above 2× a normal week",
        "Read ten source posts; drop sarcasm and mislabels",
        "Tie what’s left to tickets, outages or bills",
        "Assign one squad and a response date",
        "Check whether that issue’s share fell",
    ]
    col_w = (RIGHT - LEFT - 0.08 * 4) / 5
    for i, text in enumerate(step_text):
        add_text(s, LEFT + i * (col_w + 0.08) + 0.05, 3.5, col_w - 0.15, 1.4, text, size=14, color=INK)
    add_box(s, LEFT, 5.2, RIGHT - LEFT, 1.3, fill=TINT)
    add_text(s, LEFT + 0.3, 5.3, 4.3, 1.1, [[("2 weeks ", {"bold": True, "color": NAVY, "size": 22}),
                                            ("crossed n ≥ 115", {})]], size=16, color=INK, anchor=MSO_ANCHOR.MIDDLE)
    add_text(s, 5.4, 5.3, 7.1, 1.1, ["16 Mar: Singtel outage (352)  ·  14 Sep: multi-brand (149)",
                                    "Demo: open dashboard/index.html"],
             size=16, color=INK, anchor=MSO_ANCHOR.MIDDLE, space_after=4)

    # 22 — Section E
    deck.section("E", "Actions and reflection", "What operators should do, and what I learned", "About 4 minutes",
                 "Part E: recommendations for operators, the points I found most interesting, limitations and "
                 "next steps.")

    # 23 — Recommendations
    s = deck.content(
        "Recommendations, ordered by not-happy share",
        "The order comes from the data: each issue's share of not-happy discussion in the corpus. "
        "Network is first by far, and the huddle flagged two incident weeks, so the first action is incident "
        "communication, then proving local fixes. Plans and pricing come next: terms people discover late, "
        "like fair-use limits and Caller ID charges. Devices and the app are small but steady.\n\n"
        "Billing and customer service are the most negative by rate but small, and in the outage case study "
        "they were aftercare, so that's a plan for incidents rather than a standing priority. My earlier App "
        "& Account priority, from the 158-post sample, is withdrawn.",
    )
    recs = [
        ("1  Network", "Status page and restoration ETA during incidents; join named-location posts to tickets",
         "Faster first update; fewer tickets at that location"),
        ("2  Plans & pricing", "Show fair-use limits, add-on charges and recurring price at checkout",
         "Fewer hidden-charge threads"),
        ("3  Devices & app", "Publish router and eSIM requirements; watch posts after each app release",
         "Fewer equipment and “can’t log in” threads"),
        ("4  Incident aftercare", "Publish the compensation rule with the outage notice; keep self-service open",
         "Fewer compensation and “can’t reach support” posts"),
        ("5  Roaming, porting", "Small, mostly questions: a travel checklist and clearer port timelines",
         "No priority unless volume rises"),
        ("6  Weekly huddle", "Act only when a week reaches twice a normal week; one owner, one date",
         "That issue’s share falls next week"),
    ]
    card_w, card_h = (RIGHT - LEFT - 0.25 * 2) / 3, 2.3
    for i, (owner, action, check) in enumerate(recs):
        col, row = i % 3, i // 3
        x, y = LEFT + col * (card_w + 0.25), BODY_TOP + 0.05 + row * (card_h + 0.25)
        add_box(s, x, y, card_w, card_h, fill=GOLD_TINT if i < 2 else TINT)
        add_text(s, x + 0.25, y + 0.2, card_w - 0.5, 0.45, owner, size=18, bold=True, color=NAVY)
        add_text(s, x + 0.25, y + 0.7, card_w - 0.5, 0.95, action, size=14, color=INK)
        add_text(s, x + 0.25, y + 1.6, card_w - 0.5, 0.6, [[("Check: ", {"bold": True, "color": GOLD}),
                                                             (check, {})]], size=13, color=INK)

    # 24 — Most interesting
    s = deck.content(
        "What I found most interesting",
        "Four things surprised me.\n\n"
        "First, the bigger model didn't win on sentiment. GPT-4o ties mini at 17 times the cost, on typical "
        "and hard posts.\n\n"
        "Second, my best issue method didn't survive a held-out test. That's exactly why you keep a test set "
        "you don't tune on.\n\n"
        "Third, two gaps that looked like insights, Reddit versus HWZ and Singtel versus everyone, were one "
        "outage.\n\n"
        "Fourth, the data itself had bugs: 24,690 scraped rows held only 11,643 unique posts, and the HWZ "
        "scraper had only ever read page one of each thread until I fixed its page counter.",
    )
    insights = [
        ("The bigger model didn’t win", "GPT-4o ties mini on sentiment at ~17× the cost, on both gold sets."),
        ("My best method failed the held-out test", "Hybrid: 0.680 on the set I tuned on, 0.509 on held-out "
                                                    "posts, where GPT-4o on every post won."),
        ("Two ‘insights’ were one outage", "Reddit vs HWZ and Singtel vs StarHub both close once the 22 outage "
                                           "threads are removed."),
        ("The data had bugs too", "24,690 rows → 11,643 unique posts; HWZ scraper read only page 1 until fixed."),
    ]
    for i, (head, body) in enumerate(insights):
        y = BODY_TOP + 0.1 + i * 1.2
        badge = add_box(s, LEFT, y + 0.12, 0.62, 0.62, fill=GOLD, shape=MSO_SHAPE.OVAL)
        shape_label(badge, str(i + 1), size=18)
        add_text(s, LEFT + 0.9, y + 0.05, 4.35, 0.8, head, size=18, bold=True, color=NAVY,
                 anchor=MSO_ANCHOR.MIDDLE)
        add_text(s, 6.0, y + 0.05, 6.73, 0.8, body, size=16, color=INK, anchor=MSO_ANCHOR.MIDDLE)

    # 25 — Limitations
    s = deck.content(
        "Limitations I’d flag to any reader",
        "On the data side: forum users choose to post, so they aren't Singapore subscribers at large; replies "
        "cluster by thread; 95% of posts are from 2026; recent Reddit posts come from a research archive, which "
        "can miss deleted posts; and I have no tickets or NPS to validate against.\n\nOn the method side: "
        "mini matches my labels on about two-thirds of posts, and two humans only agree at kappa 0.39; on the "
        "recent-posts gold set sentiment holds but mini under-calls complaints and issue tagging is weaker; "
        "the hybrid's 0.680 is optimistic; and a multi-brand post gives its one sentiment to every brand.",
    )
    for x, head, items in [
        (LEFT, "Data", ["Forum posters self-select; they are not all subscribers",
                        "95% of posts from 2026; replies cluster by thread",
                        "Recent Reddit posts via a research archive",
                        "No tickets, outages or NPS to validate against"]),
        (6.8, "Method", ["Mini matches humans on ~2/3 of posts; humans agree at κ 0.39",
                         "Recent posts: sentiment holds; issues weaker (0.477)",
                         "Hybrid’s 0.680 is optimistic (0.509 held out)",
                         "One sentiment is copied to every brand in a post"]),
    ]:
        add_box(s, x, BODY_TOP + 0.05, 5.93, 4.3, fill=TINT)
        add_text(s, x + 0.3, BODY_TOP + 0.3, 5.3, 0.5, head, size=22, bold=True, color=NAVY)
        add_text(s, x + 0.3, BODY_TOP + 1.0, 5.35, 3.2, items, size=17, color=INK, bullets=True, space_after=14)

    # 26 — Next steps
    s = deck.content(
        "Next steps, in order",
        "Four next steps. One: improve issue tagging on recent posts, which scores well below the "
        "representative set, starting with customer service, and have a second annotator label part of the "
        "recent-posts gold set. Two: adjudicate the "
        "remaining disagreements between the two annotators. Three: settle hybrid versus GPT-4o on every post "
        "with a fresh held-out sample, since my gold sets disagree. Four: brand-level sentiment, so a post "
        "praising StarHub and criticising Singtel gets two labels, and validation against real tickets.",
    )
    steps = [
        ("1", "Issue tagging", "Lift recent-post issue F1 (0.477), starting with Customer Service"),
        ("2", "Adjudicate", "Resolve A–B disagreements in a separate file"),
        ("3", "Fresh held-out test", "Hybrid vs GPT-4o on every post, on new posts"),
        ("4", "Brand-level sentiment", "One label per brand per post; validate against tickets"),
    ]
    card_w = (RIGHT - LEFT - 0.25 * 3) / 4
    for i, (num, head, body) in enumerate(steps):
        x = LEFT + i * (card_w + 0.25)
        add_box(s, x, BODY_TOP + 0.3, card_w, 3.6, fill=TINT)
        badge = add_box(s, x + 0.3, BODY_TOP + 0.6, 0.8, 0.8, fill=NAVY, shape=MSO_SHAPE.OVAL)
        shape_label(badge, num, size=22)
        add_text(s, x + 0.3, BODY_TOP + 1.7, card_w - 0.6, 0.9, head, size=19, bold=True, color=NAVY)
        add_text(s, x + 0.3, BODY_TOP + 2.6, card_w - 0.6, 1.2, body, size=16, color=INK)

    # 27 — Thank you
    s = deck.strip(
        "To close: an LLM for sentiment, keyword rules plus a targeted GPT-4o pass for issues, and a weekly "
        "human huddle before anyone acts. Thank you, Professor. I'm happy to take questions, and I have "
        "backup slides with the detailed tables and agreement numbers.",
    )
    add_text(s, LEFT + 0.3, 2.0, 11.5, 1.2, "Thank you", size=48, bold=True, color=NAVY)
    add_text(s, LEFT + 0.3, 3.2, 11.5, 0.7, "Questions and discussion", size=24, color=MUTED)
    flow(s, LEFT + 0.3, 4.4, 11.8, 1.1, ["LLM for sentiment", "Rules + targeted GPT-4o for issues", "People decide"],
         size=18)

    # 28 — Backup section
    deck.section("Q", "Backup: anticipated questions", "Short answers, with the evidence behind them",
                 "For Q&A",
                 "Backup slides. I'll only show these if the question comes up.")

    qa = [
        ("Why not use GPT-4o for everything?",
         "On typical posts GPT-4o on every post ties rules (0.600 vs 0.639) and costs ~17× mini. On hard posts "
         "it wins (0.596 vs 0.499). At ~$0.0005 a post it’s affordable on a deduplicated feed; I’d settle it on "
         "fresh held-out data."),
        ("Is the hybrid’s gain real?",
         "On the set I tuned it on, yes: +0.041, 95% CI +0.011 to +0.072. On the held-out challenge set, no: "
         "+0.010, CI −0.04 to +0.07. So I report 0.680 as optimistic."),
        ("How reliable are your labels?",
         "Two annotators agree at κ 0.39 on typical posts and 0.59 on hard ones, mostly split on complaint vs "
         "neutral. The guide now has an explicit rule for failure reports."),
        ("How good is GPT-4o-mini on the corpus?",
         "F1 0.631 on the representative set and 0.637 on the recent-posts set; a rerun reproduced 292 of 295 "
         "labels. On recent posts it under-calls complaints, so not-happy is likely understated."),
        ("How do you handle sarcasm and Singlish?",
         "VADER can’t; the challenge set targets these cases. There GPT-4o-mini reaches 0.773 macro F1 vs "
         "VADER 0.491 and GPT-4o 0.712."),
        ("Why keep VADER at all?",
         "It’s free, local and deterministic: a baseline to beat. I no longer use it for any headline share."),
        ("Is Reddit more negative than HWZ? Is Singtel worst?",
         "Outside outage threads, Reddit 42% vs HWZ 37%, mostly topic mix; brands sit within 3 points (Singtel "
         "42%, StarHub 40%), with Eight lowest at 35%."),
        ("What about privacy and ethics?",
         "Public posts only, no usernames in outputs, no identifiers sent to the API, and API keys kept in "
         "environment variables, never in code."),
        ("Can this estimate NPS or market share?",
         "No. Posters self-select, replies cluster by thread, and 95% of posts are from 2026. It’s a triage "
         "queue, not a population measure."),
    ]
    qa_notes = {
        0: "If pushed on cost: the whole clean corpus with GPT-4o on every post would be about $0.85.",
        1: "Paired bootstrap, 2,000 resamples of posts. Challenge-set gain of GPT-4o over the hybrid: +0.087, "
           "CI +0.017 to +0.151.",
        2: "Per-label issue κ on the representative overlap: Network Quality 0.79, but Devices 0.16, App & "
           "Account 0.17 and Customer Service 0.28. Two earlier versions of B's sheet were superseded because "
           "they copied my labels; the one used was relabelled with B's own notes.",
        3: "Mini's weakest class is happy (F1 0.54). Corpus shares are estimates, not measurements.",
    }
    for page in range(3):
        s = deck.content(f"Anticipated questions ({page + 1} of 3)",
                         "\n\n".join(f"Q: {q}\nA: {a}" + (f"\n{qa_notes[page * 3 + j]}" if page * 3 + j in qa_notes
                                                           else "")
                                     for j, (q, a) in enumerate(qa[page * 3: page * 3 + 3])))
        for j, (q, a) in enumerate(qa[page * 3: page * 3 + 3]):
            y = BODY_TOP + j * 1.7
            add_box(s, LEFT, y, RIGHT - LEFT, 1.55, fill=TINT if j % 2 == 0 else WHITE, line=None if j % 2 == 0
                    else LINE)
            add_text(s, LEFT + 0.3, y + 0.15, 3.8, 1.25, q, size=17, bold=True, color=NAVY,
                     anchor=MSO_ANCHOR.MIDDLE)
            add_text(s, 5.0, y + 0.15, 7.5, 1.25, a, size=15, color=INK, anchor=MSO_ANCHOR.MIDDLE)

    # 32 — Agreement backup
    s = deck.content(
        "Backup: two humans split on complaint vs neutral",
        "Inter-annotator agreement on the 100 overlap posts, per set. Representative sentiment kappa is 0.39, "
        "fair; challenge is 0.59. Most disagreements are one pattern: posts I labelled not happy that the "
        "second annotator labelled neutral, typically questions about compensation, troubleshooting tips or "
        "second-hand reports. My guide never said whether a failure report is a complaint or a fact; it now "
        "does, and the second annotator's final pass applied that rule.\n\n"
        "Two earlier versions of the second annotator's sheet are superseded: the first contradicted their own "
        "notes and matched mine, the second only revised sentiment. The version used was relabelled with their "
        "own notes throughout; no notes match mine and 9 of 40 challenge rows match on every field. Issue "
        "agreement is high for network quality, 0.79, but low for devices, app and customer service.",
    )
    add_table(s, LEFT, BODY_TOP + 0.05, RIGHT - LEFT, [2.6, 1.4, 2.6, 2.3, 3.23],
              ["Set", "Posts", "Sentiment agreement", "Sentiment κ", "Issue overlap (Jaccard)"], [
                  ["Representative", "58", "62%", "0.39", "0.56"],
                  ["Challenge", "40", "73%", "0.59", "0.77"],
              ], size=16, row_h=0.6)
    callout(s, LEFT, 4.05, 5.9, 2.2, "One pattern explains most of it",
            "9 of 22 representative disagreements (8 of 11 on challenge): I said not happy, B said neutral.",
            size=15)
    callout(s, 6.83, 4.05, 5.9, 2.2, "Low human ceiling on small themes",
            "Issue κ: Network 0.79, but Devices 0.16, App 0.17, Customer Service 0.28.", size=15)

    # 33 — Per-class backup
    s = deck.content(
        "Backup: per-class sentiment metrics (n = 295)",
        "Per-class detail. VADER's weakness is not-happy recall: 0.34. GPT-4o-mini recovers 79% of complaints. "
        "GPT-4o is more conservative on happy, with recall 0.38, which is why it doesn't beat mini overall.",
    )
    add_table(s, LEFT, BODY_TOP + 0.05, RIGHT - LEFT, [2.4, 2.4, 2.0, 2.0, 1.7, 1.63],
              ["Method", "Class", "Precision", "Recall", "F1", "Support"], [
                  ["VADER", "Happy", "0.226", "0.585", "0.326", "53"],
                  ["VADER", "Not happy", "0.602", "0.340", "0.435", "147"],
                  ["VADER", "Neutral", "0.360", "0.284", "0.318", "95"],
                  ["GPT-4o-mini", "Happy", "0.574", "0.509", "0.540", "53"],
                  ["GPT-4o-mini", "Not happy", "0.753", "0.789", "0.771", "147"],
                  ["GPT-4o-mini", "Neutral", "0.585", "0.579", "0.582", "95"],
                  ["GPT-4o", "Happy", "0.690", "0.377", "0.488", "53"],
                  ["GPT-4o", "Not happy", "0.767", "0.782", "0.774", "147"],
                  ["GPT-4o", "Neutral", "0.552", "0.674", "0.607", "95"],
              ], size=14, row_h=0.47, highlight_rows=(1, 4))

    return deck.save(OUT)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the SMU-branded capstone walkthrough deck")
    parser.add_argument("--template", type=Path, default=None, help=f"SMU template .pptx (default: {DEFAULT_TEMPLATE})")
    args = parser.parse_args()
    print(f"Wrote {build(args.template)}")


if __name__ == "__main__":
    main()
