"""Real isolated parsing, content-derived locators, hostile input and process cleanup."""

import asyncio
import io
import sys
import zipfile
from dataclasses import replace

import pytest

from app.contracts import ProfileContent
from app.contracts.ports import ExtractedDocument, TextSegment
from app.intake import (
    DocumentExtractor,
    DocumentLimits,
    GatewayIntake,
    IntakeError,
    locate_document_evidence,
)
from app.intake.documents import DOCX, PDF
from tests.intake.document_fixtures import CT, W, docx_bytes, pdf_bytes
from tests.intake.test_gateway_intake import CONTEXT, StubGateway


def extract(data, media_type=PDF, **limits):
    return asyncio.run(
        DocumentExtractor(replace(DocumentLimits(), **limits)).extract(io.BytesIO(data), media_type)
    )


def assert_error(data, code, media_type=PDF, **limits):
    with pytest.raises(IntakeError) as error:
        extract(data, media_type, **limits)
    assert error.value.code == code
    return str(error.value)


def test_pdf_chinese_and_ascii_have_actual_page_locations():
    result = extract(pdf_bytes("合成简历：使用 Python 完成数据清洗。", "SQL project"))
    assert result.segments[0].text == "合成简历：使用 Python 完成数据清洗。"
    assert result.segments[1] == TextSegment("SQL project", "page:2")
    assert result.text == "\n".join(segment.text for segment in result.segments)
    assert result.warnings == ()


def test_borrowed_stream_position_and_ownership_are_preserved():
    stream = io.BytesIO(pdf_bytes("Synthetic resume"))
    stream.seek(5)
    result = asyncio.run(DocumentExtractor().extract(stream, PDF))
    assert result.text == "Synthetic resume"
    assert stream.tell() == 5
    assert not stream.closed


@pytest.mark.parametrize(
    "data,media", [(b"plain text", PDF), (pdf_bytes("PDF"), DOCX), (b"old DOC", DOCX)]
)
def test_media_type_is_checked_against_actual_bytes(data, media):
    assert_error(data, "UNSUPPORTED_FILE_TYPE", media)


def test_unsupported_type_is_rejected_without_reading_stream():
    with pytest.raises(IntakeError) as error:
        asyncio.run(DocumentExtractor().extract(None, "application/msword"))
    assert error.value.code == "UNSUPPORTED_FILE_TYPE"


@pytest.mark.parametrize("data", [b"%PDF-1.7\nnot-a-document", b"%PDF-1.7\n%%EOF"])
def test_corrupt_pdf_is_a_safe_parse_failure(data):
    message = assert_error(data, "DOCUMENT_PARSE_FAILED")
    assert "Traceback" not in message and "not-a-document" not in message


def test_encrypted_pdf_is_rejected():
    assert "加密" in assert_error(pdf_bytes("Synthetic", encrypted=True), "DOCUMENT_PARSE_FAILED")


def test_pdf_without_text_fails_instead_of_fabricating_profile():
    assert_error(pdf_bytes(""), "NO_TEXT_LAYER")
    assert_error(pdf_bytes("", image_only=True), "NO_TEXT_LAYER")


@pytest.mark.parametrize("media", [PDF, DOCX])
def test_real_document_to_existing_profile_pipeline_with_source_locations(media):
    text = "使用 Python 完成课程数据清洗项目。"
    data = (
        pdf_bytes(text) if media == PDF else docx_bytes(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>")
    )
    payload = {
        "overview": "完全虚构的测试档案。",
        "as_of_month": "2026-09",
        "facts": [
            {
                "id": "f1",
                "kind": "project",
                "label": "Python",
                "value": None,
                "polarity": "positive",
                "application": "applied",
                "start_month": None,
                "end_month": None,
                "completed": None,
                "evidence_ids": ["e1"],
            }
        ],
        "evidence": [
            {
                "id": "e1",
                "source_type": "document",
                "source_id": "doc-fixture-1",
                "quote": text,
                "locator": "invented:99",
            }
        ],
    }
    gateway = StubGateway({"profile_extract": payload})
    intake = GatewayIntake(gateway, source_id="doc-fixture-1")

    async def run():
        document = await intake.extract_document(io.BytesIO(data), media)
        return await intake.build_document_profile(document, context=CONTEXT)

    profile = asyncio.run(run())
    assert profile.evidence[0].locator == ("page:1" if media == PDF else "paragraph:1")
    assert profile.evidence[0].quote == text
    assert gateway.calls[0]["prompt_context"]["source_text"] == text
    assert gateway.calls[0]["prompt_context"]["source_id"] == "doc-fixture-1"


@pytest.mark.parametrize("value", [0, -1, True])
def test_limits_reject_invalid_file_budgets(value):
    with pytest.raises(ValueError):
        DocumentLimits(max_file_bytes=value)


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
def test_limits_reject_invalid_timeouts(value):
    with pytest.raises(ValueError):
        DocumentLimits(timeout_seconds=value)


def test_docx_duplicate_members_and_corrupt_archives_fail():
    data = docx_bytes("<w:p/>")
    stream = io.BytesIO(data)
    with pytest.warns(UserWarning):
        with zipfile.ZipFile(stream, "a") as archive:
            archive.writestr("word/document.xml", "<invalid/>")
    assert_error(stream.getvalue(), "DOCUMENT_PARSE_FAILED", DOCX)
    assert_error(b"PK\x03\x04corrupt", "DOCUMENT_PARSE_FAILED", DOCX)


def test_docx_segment_budget_is_enforced():
    data = docx_bytes("<w:p><w:r><w:t>one</w:t></w:r></w:p>" * 2)
    assert_error(data, "DOCUMENT_PARSE_FAILED", DOCX, max_segments=1)


def test_docx_corrupt_unread_media_is_not_accepted_as_an_intact_file():
    data = bytearray(
        docx_bytes(
            "<w:p><w:r><w:t>合成资料</w:t></w:r></w:p>",
            extra={"word/media/synthetic.bin": b"synthetic image bytes"},
        )
    )
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        member = archive.getinfo("word/media/synthetic.bin")
        position = member.header_offset + 30 + len(member.filename.encode()) + len(member.extra)
    data[position] ^= 0xFF
    assert_error(bytes(data), "DOCUMENT_PARSE_FAILED", DOCX)


def test_docx_auxiliary_parts_are_not_silently_claimed_as_extracted():
    data = docx_bytes(
        "<w:p><w:r><w:t>正文</w:t></w:r></w:p>",
        extra={
            "word/header1.xml": f'<w:hdr xmlns:w="{W}"><w:p><w:r><w:t>页眉</w:t></w:r></w:p></w:hdr>'.encode()
        },
    )
    result = extract(data, DOCX)
    assert result.text == "正文"
    assert any("DOCX_AUXILIARY_TEXT_NOT_EXTRACTED" in w for w in result.warnings)


def test_worker_abnormal_exit_is_a_safe_failure(monkeypatch):
    original = asyncio.create_subprocess_exec
    processes = []

    async def failed_worker(*args, **kwargs):
        process = await original(sys.executable, "-I", "-c", "raise SystemExit(23)", **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", failed_worker)
    assert_error(b"synthetic", "DOCUMENT_PARSE_FAILED")
    assert len(processes) == 1 and processes[0].returncode == 23


def test_partly_empty_pdf_warns_and_retains_original_page_numbers():
    result = extract(pdf_bytes("", "Synthetic"))
    assert result.segments == (TextSegment("Synthetic", "page:2"),)
    assert any("PDF_EMPTY_PAGES: 1" in warning for warning in result.warnings)


def test_pdf_page_limit_boundary():
    assert len(extract(pdf_bytes(*(["Page"] * 20))).segments) == 20
    assert_error(pdf_bytes(*(["Page"] * 21)), "DOCUMENT_PARSE_FAILED")


def test_file_size_and_text_limits_do_not_silently_truncate():
    data = pdf_bytes("Synthetic content")
    assert_error(data, "FILE_TOO_LARGE", max_file_bytes=len(data) - 1)
    assert extract(data, max_file_bytes=len(data)).text == "Synthetic content"
    assert_error(data, "INPUT_TOO_LONG", max_text_chars=5)


def test_compressed_pdf_content_has_an_expansion_budget():
    data = pdf_bytes("x" * 2000, compressed=True)
    assert_error(data, "DOCUMENT_PARSE_FAILED", max_unpacked_bytes=1000)


def test_docx_body_table_inline_formatting_and_locations():
    data = docx_bytes(
        "<w:p><w:r><w:t>合成简历</w:t></w:r></w:p>"
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Python</w:t></w:r>"
        "<w:r><w:tab/><w:t>数据清洗</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
        "<w:p><w:r><w:t>SQL</w:t><w:br/><w:t>项目</w:t></w:r></w:p>"
    )
    result = extract(data, DOCX)
    assert result.text == "合成简历\nPython\t数据清洗\nSQL\n项目"
    assert [s.locator for s in result.segments] == [
        "paragraph:1",
        "table:1/row:1/cell:1/paragraph:1",
        "paragraph:2",
    ]
    assert any("DOCX_PAGINATION_UNVERIFIED" in warning for warning in result.warnings)


def test_docx_insertion_is_read_but_deleted_text_is_excluded():
    result = extract(
        docx_bytes(
            "<w:p><w:del><w:r><w:delText>博士</w:delText></w:r></w:del>"
            "<w:ins><w:r><w:t>本科</w:t></w:r></w:ins></w:p>"
        ),
        DOCX,
    )
    assert result.text == "本科"
    assert any("DOCX_TRACKED_CHANGES" in warning for warning in result.warnings)


def test_docx_missing_text_is_explicit():
    assert_error(docx_bytes("<w:p><w:r><w:drawing/></w:r></w:p>"), "NO_TEXT_LAYER", DOCX)


def test_docx_does_not_trust_cached_page_count_as_layout():
    result = extract(
        docx_bytes(
            "<w:p><w:r><w:t>合成资料</w:t></w:r></w:p>",
            extra={"docProps/app.xml": b"<Properties><Pages>1</Pages></Properties>"},
        ),
        DOCX,
    )
    assert any("DOCX_PAGINATION_UNVERIFIED" in warning for warning in result.warnings)


def test_docx_rejects_explicit_page_overflow():
    data = docx_bytes(
        "<w:p><w:r><w:t>合成资料</w:t>" + '<w:br w:type="page"/>' * 20 + "</w:r></w:p>"
    )
    assert_error(data, "DOCUMENT_PARSE_FAILED", DOCX)


def test_docx_expansion_and_member_count_are_bounded():
    data = docx_bytes(
        "<w:p><w:r><w:t>合成资料</w:t></w:r></w:p>", extra={"word/media/filler.bin": b"x" * 10000}
    )
    assert len(data) < 3000
    assert_error(data, "DOCUMENT_PARSE_FAILED", DOCX, max_unpacked_bytes=3000)
    assert_error(data, "DOCUMENT_PARSE_FAILED", DOCX, max_zip_entries=2)


@pytest.mark.parametrize(
    "name", ["../escape.txt", "/absolute.txt", "C:/escape.txt", "word\\evil.xml"]
)
def test_docx_rejects_path_traversal_without_extracting_to_disk(name, tmp_path):
    data = docx_bytes("<w:p/>", extra={name: b"synthetic"})
    assert_error(data, "DOCUMENT_PARSE_FAILED", DOCX)
    assert list(tmp_path.iterdir()) == []


def test_docx_rejects_a_regular_zip_disguised_as_word():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("hello.txt", "not a DOCX")
    assert_error(stream.getvalue(), "UNSUPPORTED_FILE_TYPE", DOCX)


def test_docx_macro_type_is_not_accepted_as_docx():
    data = docx_bytes(
        "<w:p/>",
        extra={
            "[Content_Types].xml": (
                f'<Types xmlns="{CT}"><Override PartName="/word/document.xml" '
                'ContentType="application/vnd.ms-word.document.macroEnabled.main+xml"/></Types>'
            ).encode()
        },
    )
    assert_error(data, "UNSUPPORTED_FILE_TYPE", DOCX)


def test_docx_dtd_and_external_entities_are_rejected_without_leaking_data():
    malicious = (
        '<!DOCTYPE document [<!ENTITY xxe SYSTEM "file:///PRIVATE-SENTINEL">]>'
        f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>&xxe;</w:t>'
        "</w:r></w:p></w:body></w:document>"
    ).encode()
    message = assert_error(
        docx_bytes("", extra={"word/document.xml": malicious}), "DOCUMENT_PARSE_FAILED", DOCX
    )
    assert "PRIVATE-SENTINEL" not in message


def test_document_locations_come_from_source_and_do_not_mutate_profile():
    profile = ProfileContent(
        overview="合成资料",
        as_of_month="2026-10",
        facts=[],
        evidence=[
            {
                "id": "e1",
                "source_type": "document",
                "source_id": "doc-1",
                "quote": "Python",
                "locator": "invented:99",
            },
            {
                "id": "e2",
                "source_type": "message",
                "source_id": "message-1",
                "quote": "SQL",
                "locator": None,
            },
        ],
    )
    document = ExtractedDocument(
        "Python\nSQL", (TextSegment("Python", "page:1"), TextSegment("SQL", "page:2")), ()
    )
    result = locate_document_evidence(profile, document, "doc-1")
    assert result.evidence[0].locator == "page:1"
    assert result.evidence[1] == profile.evidence[1]
    assert profile.evidence[0].locator == "invented:99"
    ambiguous = replace(
        document,
        text="Python\nPython",
        segments=(TextSegment("Python", "page:1"), TextSegment("Python", "page:2")),
    )
    assert locate_document_evidence(profile, ambiguous, "doc-1").evidence[0].locator is None


def test_worker_timeout_kills_and_reaps_the_actual_process(monkeypatch):
    original = asyncio.create_subprocess_exec
    processes = []

    async def slow_worker(*args, **kwargs):
        process = await original(
            sys.executable, "-I", "-c", "import time; time.sleep(30)", **kwargs
        )
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", slow_worker)
    assert_error(b"synthetic", "DOCUMENT_PARSE_FAILED", timeout_seconds=0.1)
    assert len(processes) == 1 and processes[0].returncode is not None


def test_cancellation_kills_and_reaps_the_actual_process(monkeypatch):
    original = asyncio.create_subprocess_exec
    processes = []

    async def slow_worker(*args, **kwargs):
        process = await original(
            sys.executable, "-I", "-c", "import time; time.sleep(30)", **kwargs
        )
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", slow_worker)

    async def run():
        task = asyncio.create_task(DocumentExtractor().extract(io.BytesIO(b"synthetic"), PDF))
        while not processes:
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert processes[0].returncode is not None

    asyncio.run(run())
