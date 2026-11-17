"""Build separate student paper and answer-key PDFs with ReportLab."""

from dataclasses import dataclass
from html import escape
from io import BytesIO
from itertools import groupby

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from services.paper_patterns import PaperPattern


PDF_LAYOUT_VERSION = 4


SECTION_TITLES = {
    "MCQ": "Multiple-choice questions",
    "Short answer": "Short-answer questions",
    "Long answer": "Long-answer questions",
}


@dataclass(frozen=True)
class ExamHeader:
    paper_code: str = ""
    subject: str = ""
    session: str = ""


def _paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


def _page_footer(canvas, document) -> None:
    canvas.saveState()
    canvas.setFillColor(colors.grey)
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(A4[0] - 20 * mm, 12 * mm, f"Page {document.page}")
    canvas.restoreState()


def _midterm_table(questions: list[dict], pattern: PaperPattern, width: float) -> Table:
    question_style = ParagraphStyle("IpuQuestion", fontName="Times-Roman", fontSize=11, leading=14)
    outcome_style = ParagraphStyle("IpuOutcome", parent=question_style, alignment=TA_CENTER)
    rows = [("Q. No.", "Question", "Marks", "CO(s)")]
    commands = [
        ("FONTNAME", (0, 0), (-1, -1), "Times-Roman"),
        ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#aeb6bf")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (2, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    numbered_questions = zip(pattern.slots, questions)
    for _, parts in groupby(numbered_questions, key=lambda part: part[0].number.split("(")[0]):
        first_row = len(rows)
        for slot, item in parts:
            rows.append((
                slot.number, _paragraph(item["question"], question_style), f"{slot.marks:g}",
                _paragraph(item["course_outcomes"], outcome_style) if item.get("course_outcomes") else "",
            ))
        last_row = len(rows) - 1
        if first_row > 1:
            commands.append(("LINEABOVE", (0, first_row), (-1, first_row), 0.8, colors.HexColor("#737d87")))
            commands.append(("NOSPLIT", (0, first_row), (-1, last_row)))
    return Table(
        rows, colWidths=(48, width - 150, 44, 58), repeatRows=1,
        style=TableStyle(commands), hAlign="CENTER",
    )


def _ipu_header(pattern: PaperPattern, header: ExamHeader, width: float) -> KeepTogether:
    body = ParagraphStyle("ExamDetails", fontName="Times-Bold", fontSize=11, leading=14)
    enrolment = ParagraphStyle("ExamEnrolment", parent=body, fontName="Times-Roman")
    right = ParagraphStyle("ExamEnrolmentRight", parent=enrolment, alignment=TA_RIGHT)
    centred = ParagraphStyle("ExamCentred", parent=body, alignment=TA_CENTER, spaceAfter=5)
    title = ParagraphStyle("ExamTitle", parent=centred, fontSize=19, leading=23)
    columns = (width * 0.52, width * 0.48)
    flush_cells = [
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    midterm = pattern.table_layout
    reminder = "(Please write your Enrolment No. immediately)" if midterm else "(Please write your Exam Roll No.)"
    number_label = "Enrolment No." if midterm else "Exam Roll No."
    enrolment_row = Table(
        [[
            _paragraph(reminder, enrolment),
            _paragraph(f"{number_label} ______________", right),
        ]],
        colWidths=columns, style=TableStyle(flush_cells),
    )
    detail_style = flush_cells if midterm else [
        *flush_cells,
        ("BOX", (0, 0), (-1, 0), 0.6, colors.black),
        ("LEFTPADDING", (0, 0), (-1, 0), 4),
        ("RIGHTPADDING", (0, 0), (-1, 0), 4),
        ("TOPPADDING", (0, 0), (-1, 0), 4),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
    ]
    details = Table(
        [
            [
                _paragraph(f"Paper Code: {header.paper_code or '________________'}", body),
                _paragraph(f"Subject: {header.subject or '_______________________'}", body),
            ],
            [
                _paragraph(f"Time: {pattern.duration}", body),
                _paragraph(f"Max. Marks: {pattern.maximum_marks:g}", body),
            ],
        ],
        colWidths=columns, style=TableStyle(detail_style),
    )
    note = pattern.summary
    if midterm:
        note += " Answer both parts of each chosen question."
    else:
        note = "Attempt five questions in all, including compulsory Q1. Select one question from each unit."
    note_row = Table(
        [[_paragraph(f"Note: {note}", body if midterm else centred)]], colWidths=(width,),
        style=TableStyle([
            ("LINEABOVE", (0, 0), (-1, -1), 0.5, colors.grey),
            ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.grey),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]),
    )
    header_content = [
        enrolment_row, Spacer(1, 9),
        _paragraph(pattern.exam_title, title),
    ]
    if midterm:
        header_content.append(_paragraph("B.TECH PROGRAMMES (UNDER THE AEGIS OF USICT)", centred))
    session = header.session or "Semester / Exam Session: ____________________"
    header_content.append(_paragraph(session if midterm else f"{session} [B.TECH]", centred))
    header_content.extend([Spacer(1, 5), details, Spacer(1, 8), note_row])
    return KeepTogether(header_content)


def _endterm_questions(questions: list[dict], pattern: PaperPattern, width: float) -> list:
    body = ParagraphStyle("EndtermBody", fontName="Times-Roman", fontSize=11, leading=15)
    marks = ParagraphStyle("EndtermMarks", parent=body, alignment=TA_RIGHT)
    unit = ParagraphStyle(
        "EndtermUnit", parent=body, fontName="Times-Bold", alignment=TA_CENTER,
        spaceBefore=10, spaceAfter=6, keepWithNext=True,
    )
    row_style = TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ])
    remaining = iter(questions)
    story = []
    for group in pattern.groups:
        compulsory = not group.slots[0].unit
        if compulsory:
            heading = ParagraphStyle("EndtermCompulsory", parent=unit, alignment=0)
            story.append(_paragraph(f"Q1. {group.instruction} (5 × 5 = 25)", heading))
        else:
            story.append(_paragraph(group.title.upper(), unit))
        for slot in group.slots:
            item = next(remaining)
            number = slot.number.removeprefix("Q1") if compulsory else f"{slot.number}."
            story.append(Table(
                [[_paragraph(number, body), _paragraph(item["question"], body),
                  _paragraph(f"({slot.marks:g})", marks)]],
                colWidths=(36, width - 77, 41), style=row_style,
            ))
    return story


def _build(
    questions: list[dict],
    paper_title: str,
    instructions: str,
    include_student_fields: bool,
    answer_key: bool,
    pattern: PaperPattern | None,
    exam_header: ExamHeader | None,
) -> bytes:
    buffer = BytesIO()
    heading = pattern.exam_title if pattern else paper_title
    title = f"{heading} - Answer Key" if answer_key else heading
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title=title,
        author="QnaGen",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="QTitle", parent=styles["Title"], alignment=TA_CENTER, spaceAfter=14))
    styles.add(ParagraphStyle(name="QBody", parent=styles["BodyText"], leading=15, spaceAfter=6))
    styles.add(ParagraphStyle(name="QMeta", parent=styles["BodyText"], fontSize=8, textColor=colors.grey))
    styles.add(ParagraphStyle(name="QSection", parent=styles["Heading2"], fontSize=11, spaceBefore=12, spaceAfter=8))
    if pattern and not answer_key:
        story = [_ipu_header(pattern, exam_header or ExamHeader(), doc.width - 12)]
    else:
        story = [_paragraph(title, styles["QTitle"])]
    if pattern and answer_key:
        story.append(_paragraph(
            f"{pattern.label}  |  Time: {pattern.duration}  |  Maximum marks: {pattern.maximum_marks:g}",
            styles["QBody"],
        ))
        if exam_header:
            details = "  |  ".join(value for value in (
                exam_header.paper_code, exam_header.subject, exam_header.session,
            ) if value)
            if details:
                story.append(_paragraph(details, styles["QBody"]))
    if not answer_key:
        if include_student_fields:
            story.append(_paragraph("Name: ____________________    Date: ______________", styles["QBody"]))
        if instructions:
            story.append(_paragraph(f"Instructions: {instructions}", styles["QBody"]))
        story.append(Spacer(1, 8))

    if pattern and not answer_key:
        width = doc.width - 12
        if pattern.table_layout:
            story.append(_midterm_table(questions, pattern, width))
        else:
            story.extend(_endterm_questions(questions, pattern, width))
        doc.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
        return buffer.getvalue()

    rows = []
    if pattern:
        remaining = iter(questions)
        for group in pattern.groups:
            for index, slot in enumerate(group.slots):
                heading = group.title if index == 0 else ""
                rule = group.instruction if heading and not answer_key else ""
                rows.append((heading, rule, slot.number, f" [{slot.marks:g} marks]", next(remaining)))
    else:
        number = 0
        for section_number, (kind, items) in enumerate(groupby(questions, key=lambda q: q["type"]), 1):
            for index, item in enumerate(items):
                number += 1
                heading = f"Section {chr(64 + section_number)}: {SECTION_TITLES[kind]}" if index == 0 else ""
                rows.append((heading, "", str(number), "", item))

    for heading, rule, number, marks, item in rows:
        block = []
        if heading:
            block.append(_paragraph(heading, styles["QSection"]))
        if rule:
            block.append(_paragraph(rule, styles["QBody"]))
        block.append(_paragraph(f"{number}. {item['question']}{marks}", styles["QBody"]))
        if answer_key:
            block.append(_paragraph(f"{item['type']}  |  {item['difficulty']}", styles["QMeta"]))
        if item["type"] == "MCQ" and not answer_key:
            block.extend(_paragraph(f"{letter}. {item['options'][letter]}", styles["QBody"]) for letter in "ABCD")
        if answer_key:
            answer = item["answer"]
            if item["type"] == "MCQ":
                answer = f"{answer}. {item['options'][answer]}"
            block.append(_paragraph(f"Answer: {answer}", styles["QBody"]))
        block.append(Spacer(1, 10))
        story.append(KeepTogether(block))
    doc.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    return buffer.getvalue()


def build_pdfs(
    questions: list[dict],
    paper_title: str = "Question Paper",
    instructions: str = "",
    include_student_fields: bool = False,
    *,
    pattern: PaperPattern | None = None,
    exam_header: ExamHeader | None = None,
) -> tuple[bytes, bytes]:
    if pattern:
        pattern.check_questions(questions)
    return (
        _build(questions, paper_title, instructions, include_student_fields, False, pattern, exam_header),
        _build(questions, paper_title, instructions, include_student_fields, True, pattern, exam_header),
    )
