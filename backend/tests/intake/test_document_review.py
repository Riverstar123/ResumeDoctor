"""Real DOCX regressions for PR #49's table reading and evidence locations."""

from xml.sax.saxutils import escape

import pytest

from app.contracts import ProfileContent
from app.contracts.ports import ExtractedDocument, TextSegment
from app.intake import IntakeError, locate_document_evidence
from app.intake.documents import DOCX
from tests.intake.document_fixtures import docx_bytes
from tests.intake.test_documents import assert_error, extract


def paragraph(text):
    runs = "<w:br/>".join(f"<w:t>{escape(line)}</w:t>" for line in text.split("\n"))
    return f"<w:p><w:r>{runs}</w:r></w:p>"


def control(content):
    return f"<w:sdt><w:sdtPr/><w:sdtContent>{content}</w:sdtContent></w:sdt>"


def cell(text):
    return f"<w:tc>{paragraph(text)}</w:tc>"


def row(text):
    return f"<w:tr>{cell(text)}</w:tr>"


def table_with_control(level, text):
    contents = control(row(text)) if level == "row" else f"<w:tr>{control(cell(text))}</w:tr>"
    return f"<w:tbl>{contents}</w:tbl>"


@pytest.mark.parametrize("level", ["row", "cell"])
@pytest.mark.parametrize("with_introduction", [False, True])
def test_docx_reads_row_and_cell_content_controls(level, with_introduction):
    intro = paragraph("Visible introduction") if with_introduction else ""
    document = extract(docx_bytes(intro + table_with_control(level, "Python SQL experience")), DOCX)
    expected = "Visible introduction\n" if with_introduction else ""
    assert document.text == expected + "Python SQL experience"
    assert document.segments[-1].locator == "table:1/row:1/cell:1/paragraph:1"


def test_docx_controlled_and_plain_table_members_keep_order_and_nested_locations():
    nested = table_with_control("row", "Nested Python")
    controlled_cell = control(
        "<w:tc>" + paragraph("Before nested") + nested + paragraph("After nested") + "</w:tc>"
    )
    first_row = "<w:tr>" + cell("First") + controlled_cell + cell("Last cell") + "</w:tr>"
    second_row = control("<w:tr>" + control(cell("Second row")) + cell("SQL") + "</w:tr>")
    body = "<w:tbl>" + first_row + second_row + row("Third row") + "</w:tbl>"
    document = extract(docx_bytes(body), DOCX)
    assert document.text.splitlines() == [
        "First",
        "Before nested",
        "Nested Python",
        "After nested",
        "Last cell",
        "Second row",
        "SQL",
        "Third row",
    ]
    assert [s.locator for s in document.segments] == [
        "table:1/row:1/cell:1/paragraph:1",
        "table:1/row:1/cell:2/paragraph:1",
        "table:1/row:1/cell:2/table:1/row:1/cell:1/paragraph:1",
        "table:1/row:1/cell:2/paragraph:2",
        "table:1/row:1/cell:3/paragraph:1",
        "table:1/row:2/cell:1/paragraph:1",
        "table:1/row:2/cell:2/paragraph:1",
        "table:1/row:3/cell:1/paragraph:1",
    ]


@pytest.mark.parametrize("level", ["row", "cell"])
def test_docx_table_wrappers_preserve_revision_filtering(level):
    member = row if level == "row" else cell
    contents = "".join(
        f"<w:{tag}>{control(member(text))}</w:{tag}>"
        for tag, text in [
            ("del", "Deleted"),
            ("moveFrom", "Moved away"),
            ("ins", "Inserted"),
            ("moveTo", "Moved here"),
        ]
    ) + member("Unchanged")
    if level == "cell":
        contents = f"<w:tr>{contents}</w:tr>"
    document = extract(docx_bytes(f"<w:tbl>{contents}</w:tbl>"), DOCX)
    assert document.text == "Inserted\nMoved here\nUnchanged"
    expected = (
        [f"table:1/row:{i}/cell:1/paragraph:1" for i in range(1, 4)]
        if level == "row"
        else [f"table:1/row:1/cell:{i}/paragraph:1" for i in range(1, 4)]
    )
    assert [s.locator for s in document.segments] == expected
    assert any("DOCX_TRACKED_CHANGES" in warning for warning in document.warnings)


@pytest.mark.parametrize("level", ["row", "cell"])
def test_docx_table_wrapper_depth_is_bounded(level):
    content = row("Deep text") if level == "row" else cell("Deep text")
    for _ in range(40):
        content = control(content)
    if level == "cell":
        content = f"<w:tr>{content}</w:tr>"
    body = paragraph("Visible introduction") + f"<w:tbl>{content}</w:tbl>"
    message = assert_error(docx_bytes(body), "DOCUMENT_PARSE_FAILED", DOCX)
    assert "嵌套过深" in message


@pytest.mark.parametrize(
    "limits,code",
    [({"max_segments": 1}, "DOCUMENT_PARSE_FAILED"), ({"max_text_chars": 5}, "INPUT_TOO_LONG")],
)
def test_docx_controlled_table_text_counts_toward_budgets(limits, code):
    body = paragraph("Intro") + table_with_control("cell", "Python SQL experience")
    assert_error(docx_bytes(body), code, DOCX, **limits)


def evidence_profile(quote):
    return ProfileContent(
        overview="Synthetic profile",
        as_of_month="2026-10",
        facts=[],
        evidence=[
            {
                "id": "e1",
                "source_type": "document",
                "source_id": "doc-1",
                "quote": quote,
                "locator": "model-guess",
            },
            {
                "id": "e2",
                "source_type": "document",
                "source_id": "other-document",
                "quote": quote,
                "locator": "keep-other-document",
            },
            {
                "id": "e3",
                "source_type": "message",
                "source_id": "message-1",
                "quote": quote,
                "locator": "keep-message",
            },
        ],
    )


@pytest.mark.parametrize(
    "paragraphs,quote,expected",
    [
        (["Python", "SQL", "Python\nSQL"], "Python\nSQL", None),
        (["Python", "SQL"], "Python\nSQL", None),
        (["Python\nSQL", "Other"], "Python\nSQL", "paragraph:1"),
        (["Python Python"], "Python", None),
        (["aaa"], "aa", None),
        (["Python", "Python"], "Python", None),
        (["SQL", "Python"], "Python", "paragraph:2"),
        (["Python SQL"], "SQL", "paragraph:1"),
        (["SQL Python"], "SQL", "paragraph:1"),
        (["First", "Python\nSQL", "Last"], "Python\nSQL", "paragraph:2"),
    ],
)
def test_real_docx_locations_require_one_global_match_within_one_segment(
    paragraphs, quote, expected
):
    document = extract(docx_bytes("".join(paragraph(text) for text in paragraphs)), DOCX)
    profile = evidence_profile(quote)
    before = profile.model_dump()
    result = locate_document_evidence(profile, document, "doc-1")
    assert result.evidence[0].locator == expected
    assert result.evidence[0].quote == quote
    assert result.evidence[1:] == profile.evidence[1:]
    assert profile.model_dump() == before


def test_locations_do_not_guess_offsets_for_inconsistent_segments():
    document = ExtractedDocument("Intro\nPython", (TextSegment("Python", "paragraph:1"),), ())
    result = locate_document_evidence(evidence_profile("Python"), document, "doc-1")
    assert result.evidence[0].locator is None


def test_locations_still_reject_quotes_missing_from_source():
    document = ExtractedDocument("Python", (TextSegment("Python", "paragraph:1"),), ())
    with pytest.raises(IntakeError) as error:
        locate_document_evidence(evidence_profile("Missing"), document, "doc-1")
    assert error.value.code == "QUOTE_NOT_IN_SOURCE"
