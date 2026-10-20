"""A's PR #49 regressions: current cell revisions and one compatible branch."""

import pytest

from app.intake import locate_document_evidence
from app.intake.documents import DOCX
from tests.intake.document_fixtures import W, docx_bytes
from tests.intake.test_document_review import control, evidence_profile, paragraph
from tests.intake.test_documents import assert_error, extract

MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
SHAPE = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
STRICT_W = "http://purl.oclc.org/ooxml/wordprocessingml/main"
UNKNOWN = "urn:synthetic:unsupported"
DELETE = '<w:cellDel w:id="1" w:author="Synthetic"/>'


def cell(content, properties=""):
    return f"<w:tc>{properties}{content}</w:tc>"


def table(*cells):
    return "<w:tbl><w:tr>" + "".join(cells) + "</w:tr></w:tbl>"


def document(body, namespace=W):
    xml = f'<w:document xmlns:w="{namespace}"><w:body>{body}</w:body></w:document>'
    return docx_bytes(body, extra={"word/document.xml": xml.encode()})


def alternate(choices, fallback=None, declarations=""):
    branches = "".join(
        f'<mc:Choice Requires="{requires}">{content}</mc:Choice>' for requires, content in choices
    )
    if fallback is not None:
        branches += f"<mc:Fallback>{fallback}</mc:Fallback>"
    return (
        f'<mc:AlternateContent xmlns:mc="{MC}" xmlns:wps="{SHAPE}" '
        f'xmlns:future="{UNKNOWN}" {declarations}>{branches}</mc:AlternateContent>'
    )


def textbox(text, *, modern):
    content = f"<w:txbxContent>{paragraph(text)}</w:txbxContent>"
    if modern:
        return (
            f'<w:r><w:drawing><wps:wsp xmlns:wps="{SHAPE}">'
            f"<wps:txbx>{content}</wps:txbx></wps:wsp></w:drawing></w:r>"
        )
    return (
        '<w:r><w:pict><v:shape xmlns:v="urn:schemas-microsoft-com:vml">'
        f"<v:textbox>{content}</v:textbox></v:shape></w:pict></w:r>"
    )


@pytest.mark.parametrize("namespace", [W, STRICT_W])
@pytest.mark.parametrize("wrapped", [False, True])
def test_current_cell_deletion_is_excluded_and_warns(namespace, wrapped):
    deleted = cell(paragraph("Deleted Python skill"), f"<w:tcPr>{DELETE}</w:tcPr>")
    if wrapped:
        deleted = control(deleted)
    body = table(cell(paragraph("Before")), deleted, cell(paragraph("After")))
    result = extract(document(body, namespace), DOCX)
    assert result.text == "Before\nAfter"
    assert [s.locator for s in result.segments] == [
        "table:1/row:1/cell:1/paragraph:1",
        "table:1/row:1/cell:2/paragraph:1",
    ]
    assert any("DOCX_TRACKED_CHANGES" in warning for warning in result.warnings)


def test_historical_cell_deletion_does_not_delete_current_cell():
    properties = (
        '<w:tcPr><w:tcPrChange w:id="2" w:author="Synthetic">'
        f"<w:tcPr>{DELETE}</w:tcPr></w:tcPrChange></w:tcPr>"
    )
    result = extract(document(table(cell(paragraph("Current Python"), properties))), DOCX)
    assert result.text == "Current Python"


@pytest.mark.parametrize("current", [False, True])
def test_current_row_deletion_and_historical_row_properties_are_distinct(current):
    marker = '<w:del w:id="1" w:author="Synthetic"/>'
    if not current:
        marker = (
            '<w:trPrChange w:id="2" w:author="Synthetic"><w:trPr>'
            + marker
            + "</w:trPr></w:trPrChange>"
        )
    row = "<w:tr><w:trPr>" + marker + "</w:trPr>" + cell(paragraph("Revision row")) + "</w:tr>"
    body = paragraph("Intro") + "<w:tbl>" + row + "</w:tbl>"
    result = extract(document(body), DOCX)
    assert result.text == ("Intro" if current else "Intro\nRevision row")
    assert any("DOCX_TRACKED_CHANGES" in warning for warning in result.warnings)


@pytest.mark.parametrize("requires,expected", [("wps", "Intro"), ("future", "Intro\nCurrent")])
def test_compatible_cell_properties_are_selected_before_deletion(requires, expected):
    properties = "<w:tcPr>" + alternate([(requires, DELETE)], "") + "</w:tcPr>"
    result = extract(
        document(paragraph("Intro") + table(cell(paragraph("Current"), properties))), DOCX
    )
    assert result.text == expected


def test_nested_deleted_cell_does_not_delete_its_parent():
    nested = table(
        cell(paragraph("Deleted"), f"<w:tcPr>{DELETE}</w:tcPr>"),
        cell(paragraph("Nested current")),
    )
    result = extract(document(table(cell(paragraph("Before") + nested + paragraph("After")))), DOCX)
    assert result.text == "Before\nNested current\nAfter"
    assert result.segments[1].locator == "table:1/row:1/cell:1/table:1/row:1/cell:1/paragraph:1"


def test_document_with_only_deleted_cells_has_no_current_text():
    body = table(cell(paragraph("Deleted"), f"<w:tcPr>{DELETE}</w:tcPr>"))
    assert_error(document(body), "NO_TEXT_LAYER", DOCX)


def test_deleted_cell_page_breaks_do_not_reject_current_document():
    deleted = '<w:p><w:r><w:br w:type="page"/></w:r></w:p>' * 20
    body = table(cell(paragraph("Visible")), cell(deleted, f"<w:tcPr>{DELETE}</w:tcPr>"))
    assert extract(document(body), DOCX, max_pages=1).text == "Visible"


def test_historical_properties_do_not_supply_text_or_page_breaks():
    history = (
        '<w:pPr><w:pPrChange w:id="1" w:author="Synthetic"><w:pPr>'
        + paragraph("Historical metadata")
        + '<w:br w:type="page"/>' * 20
        + "</w:pPr></w:pPrChange></w:pPr>"
    )
    body = "<w:p>" + history + "<w:r><w:t>Current</w:t></w:r></w:p>"
    assert extract(document(body), DOCX, max_pages=1).text == "Current"


def test_a_review_real_word_structure_reads_textbox_once():
    box = alternate([("wps", textbox("MARKW", modern=True))], textbox("MARKW", modern=False))
    body = paragraph("debut") + table(cell(f"<w:p>{box}</w:p>"), cell(paragraph("b")))
    result = extract(document(body + paragraph("fin")), DOCX)
    assert result.text == "debut\nMARKW\nb\nfin"
    located = locate_document_evidence(evidence_profile("MARKW"), result, "doc-1")
    assert located.evidence[0].locator == "table:1/row:1/cell:1/paragraph:1"


@pytest.mark.parametrize("level", ["paragraph", "body", "row", "cell"])
def test_alternate_branch_selection_is_consistent_across_table_and_block_levels(level):
    content = paragraph("Selected")
    fallback = paragraph("Unselected")
    if level == "paragraph":
        body = "<w:p>" + alternate([("wps", content)], fallback) + "</w:p>"
    elif level == "body":
        body = alternate([("wps", content)], fallback)
    elif level == "row":
        body = (
            "<w:tbl>"
            + alternate(
                [("wps", "<w:tr>" + cell(content) + "</w:tr>")],
                "<w:tr>" + cell(fallback) + "</w:tr>",
            )
            + "</w:tbl>"
        )
    else:
        body = table(alternate([("wps", cell(content))], cell(fallback)))
    assert extract(document(body), DOCX).text == "Selected"


@pytest.mark.parametrize(
    "choices,fallback,declarations,expected",
    [
        ([("wps", "First"), ("wps", "Second")], "Fallback", "", "First"),
        ([("future", "Future"), ("wps", "Supported")], "Fallback", "", "Supported"),
        ([("wps future", "Needs both")], "Fallback", "", "Fallback"),
        ([("missing", "Undeclared")], "Fallback", "", "Fallback"),
        ([("alias", "Alias")], "Fallback", f'xmlns:alias="{SHAPE}"', "Alias"),
        ([("alias", "Unsupported")], "Fallback", f'xmlns:alias="{UNKNOWN}"', "Fallback"),
        ([("wps", "Selected")], None, "", "Selected"),
        ([("wps w", "Both supported")], "Fallback", "", "Both supported"),
    ],
)
def test_choices_use_first_fully_supported_namespace_set(choices, fallback, declarations, expected):
    body = alternate(
        [(requires, paragraph(text)) for requires, text in choices],
        None if fallback is None else paragraph(fallback),
        declarations,
    )
    assert extract(document(body), DOCX).text == expected


def test_choice_namespace_rebinding_is_local_to_each_branch():
    body = (
        f'<mc:AlternateContent xmlns:mc="{MC}" xmlns:feature="{SHAPE}">'
        f'<mc:Choice xmlns:feature="{UNKNOWN}" Requires="feature">{paragraph("Wrong")}'
        f'</mc:Choice><mc:Choice Requires="feature">{paragraph("Right")}</mc:Choice>'
        f"<mc:Fallback>{paragraph('Fallback')}</mc:Fallback></mc:AlternateContent>"
    )
    assert extract(document(body), DOCX).text == "Right"


def test_unsupported_alternative_without_fallback_fails_explicitly():
    body = paragraph("Intro") + alternate([("future", paragraph("Unsupported"))])
    assert_error(document(body), "DOCUMENT_PARSE_FAILED", DOCX)


def test_supported_empty_choice_does_not_read_its_fallback():
    body = paragraph("Intro") + alternate([("wps", "")], paragraph("Inactive fallback"))
    assert extract(document(body), DOCX).text == "Intro"


@pytest.mark.parametrize(
    "branches",
    [
        "<mc:Fallback/>",
        "<mc:Choice/>",
        '<mc:Choice Requires="wps"/><mc:Fallback/><mc:Fallback/>',
        '<mc:Choice Requires="wps"/><mc:Fallback/><mc:Choice Requires="wps"/>',
        '<mc:Choice Requires="wps"/><mc:Unexpected/>',
    ],
)
def test_malformed_alternatives_fail_instead_of_silently_omitting_content(branches):
    body = (
        paragraph("Intro")
        + f'<mc:AlternateContent xmlns:mc="{MC}" xmlns:wps="{SHAPE}">'
        + branches
        + "</mc:AlternateContent>"
    )
    assert_error(document(body), "DOCUMENT_PARSE_FAILED", DOCX)


@pytest.mark.parametrize("same_paragraph", [False, True])
def test_independent_same_text_boxes_are_both_retained(same_paragraph):
    box = alternate([("wps", textbox("MARKW", modern=True))], textbox("MARKW", modern=False))
    body = f"<w:p>{box}{box}</w:p>" if same_paragraph else f"<w:p>{box}</w:p>" * 2
    result = extract(document(body), DOCX)
    assert result.text == ("MARKWMARKW" if same_paragraph else "MARKW\nMARKW")
    assert (
        locate_document_evidence(evidence_profile("MARKW"), result, "doc-1").evidence[0].locator
        is None
    )


def test_only_selected_branch_contributes_page_breaks_and_revision_warnings():
    inactive = (
        '<w:del w:id="1" w:author="Synthetic">'
        + paragraph("Deleted")
        + "</w:del>"
        + '<w:p><w:r><w:br w:type="page"/></w:r></w:p>' * 20
    )
    result = extract(
        document(alternate([("wps", paragraph("Current"))], inactive)), DOCX, max_pages=1
    )
    assert result.text == "Current"
    assert not any("DOCX_TRACKED_CHANGES" in warning for warning in result.warnings)


def test_selected_branch_page_overflow_still_fails():
    selected = paragraph("Current") + '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'
    assert_error(
        document(alternate([("wps", selected)], paragraph("Fallback"))),
        "DOCUMENT_PARSE_FAILED",
        DOCX,
        max_pages=1,
    )


def test_selected_content_retains_text_and_segment_limits():
    body = alternate([("wps", paragraph("MARKW"))], paragraph("MARKW"))
    assert extract(document(body), DOCX, max_text_chars=5, max_segments=1).text == "MARKW"
    assert_error(document(body), "INPUT_TOO_LONG", DOCX, max_text_chars=4)
    body = alternate([("wps", paragraph("A") + paragraph("B"))], paragraph("Fallback"))
    assert_error(document(body), "DOCUMENT_PARSE_FAILED", DOCX, max_segments=1)


def test_alternate_nesting_keeps_the_depth_limit():
    body = paragraph("Deep")
    for _ in range(70):
        body = alternate([("wps", body)], paragraph("Fallback"))
    assert_error(document(paragraph("Intro") + body), "DOCUMENT_PARSE_FAILED", DOCX)
