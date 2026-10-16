"""Pure, offline parsers used only inside the bounded document worker."""

import io
import stat
import zipfile
from pathlib import PurePosixPath

from defusedxml import ElementTree

from app.contracts.ports import ExtractedDocument, TextSegment

from .documents import DOCX, PDF, DocumentLimits
from .errors import IntakeError

WORD_NAMESPACES = {
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "http://purl.oclc.org/ooxml/wordprocessingml/main",
}
CONTENT_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"
RELATIONSHIPS = "http://schemas.openxmlformats.org/package/2006/relationships"
MAIN_DOCUMENT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
DOCX_PAGINATION_WARNING = (
    "DOCX_PAGINATION_UNVERIFIED: 已检查明确分页；实际排版页数未经核验，需要准确页数时请另存为 PDF。"
)


def fail(message: str) -> None:
    raise IntakeError("DOCUMENT_PARSE_FAILED", message)


class TextBuilder:
    def __init__(self, limits: DocumentLimits):
        self.limits = limits
        self.segments: list[TextSegment] = []
        self.length = 0

    def add(self, text: str, locator: str):
        text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            return
        self.length += len(text) + bool(self.segments)
        if self.length > self.limits.max_text_chars:
            raise IntakeError("INPUT_TOO_LONG", "文件文字超过提取长度限制，请缩减内容后重试。")
        if len(self.segments) >= self.limits.max_segments:
            fail("文件段落过多，请简化文件后重试。")
        self.segments.append(TextSegment(text=text, locator=locator))

    def finish(self, warnings: list[str]) -> ExtractedDocument:
        if not self.segments:
            raise IntakeError(
                "NO_TEXT_LAYER", "文件没有可读取的文字，请换文字版文件或使用对话输入。"
            )
        return ExtractedDocument(
            text="\n".join(segment.text for segment in self.segments),
            segments=tuple(self.segments),
            warnings=tuple(warnings),
        )


def parse_document(data: bytes, media_type: str, limits: DocumentLimits) -> ExtractedDocument:
    if len(data) > limits.max_file_bytes:
        raise IntakeError("FILE_TOO_LARGE", "文件超过大小限制，请缩减后重试。")
    if media_type == PDF:
        if not data.startswith(b"%PDF-"):
            raise IntakeError("UNSUPPORTED_FILE_TYPE", "文件内容与 PDF 格式不符。")
        return parse_pdf(data, limits)
    if media_type == DOCX:
        if not data.startswith(b"PK\x03\x04"):
            raise IntakeError("UNSUPPORTED_FILE_TYPE", "文件内容与 DOCX 格式不符。")
        return parse_docx(data, limits)
    raise IntakeError("UNSUPPORTED_FILE_TYPE", "仅支持文字 PDF 和 DOCX 文件。")


def parse_pdf(data: bytes, limits: DocumentLimits) -> ExtractedDocument:
    # These globals are set only in the disposable parser process, never in the API.
    from pypdf import PdfReader, filters

    for name in (
        "ZLIB_MAX_OUTPUT_LENGTH",
        "LZW_MAX_OUTPUT_LENGTH",
        "RUN_LENGTH_MAX_OUTPUT_LENGTH",
        "MAX_ARRAY_BASED_STREAM_OUTPUT_LENGTH",
        "MAX_DECLARED_STREAM_LENGTH",
        "FLATE_MAX_BUFFER_SIZE",
        "JBIG2_MAX_OUTPUT_LENGTH",
    ):
        setattr(filters, name, min(getattr(filters, name), limits.max_unpacked_bytes))
    reader = PdfReader(io.BytesIO(data), strict=True)
    if reader.is_encrypted:
        fail("文件已加密，请去除密码后重新上传。")
    pages = len(reader.pages)
    if pages > limits.max_pages:
        fail("PDF 页数超过限制，请缩减后重试。")
    builder = TextBuilder(limits)
    empty_pages = []
    expanded = 0
    for index, page in enumerate(reader.pages, 1):
        contents = page.get_contents()
        if contents is not None:
            expanded += len(contents.get_data())
            if expanded > limits.max_unpacked_bytes:
                fail("PDF 内容展开后超过安全限制，请简化文件。")
        text = page.extract_text() or ""
        if not text.strip():
            empty_pages.append(str(index))
        builder.add(text, f"page:{index}")
    warnings = []
    if empty_pages:
        warnings.append(
            "PDF_EMPTY_PAGES: " + ",".join(empty_pages) + "；这些页面未提取到文字，请核对。"
        )
    if any("\ufffd" in segment.text for segment in builder.segments):
        warnings.append("PDF_TEXT_ENCODING_UNCERTAIN: 文字包含无法识别的字符，请核对或改用 Word。")
    return builder.finish(warnings)


def _xml(data: bytes):
    return ElementTree.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)


def _word_name(element) -> str:
    if element.tag.startswith("{"):
        namespace, name = element.tag[1:].split("}", 1)
        if namespace in WORD_NAMESPACES:
            return name
    return ""


def _attribute(element, name: str) -> str | None:
    for namespace in WORD_NAMESPACES:
        value = element.get("{" + namespace + "}" + name)
        if value is not None:
            return value
    return None


def _paragraph_text(element) -> str:
    output = []
    pending = [element]
    while pending:
        node = pending.pop()
        name = _word_name(node)
        if name in {"del", "moveFrom"}:
            continue
        if name == "t":
            output.append(node.text or "")
        elif name == "tab":
            output.append("\t")
        elif name in {"br", "cr"}:
            output.append("\n")
        pending.extend(reversed(list(node)))
    return "".join(output)


def _blocks(container, builder: TextBuilder, prefix: str = "", depth: int = 0):
    if depth > 64:
        fail("Word 内容嵌套过深，请简化文件。")
    paragraph = 0
    table = 0
    for index, node in enumerate(container, 1):
        name = _word_name(node)
        if name in {"del", "moveFrom", "sectPr"}:
            continue
        if name == "p":
            paragraph += 1
            builder.add(_paragraph_text(node), f"{prefix}paragraph:{paragraph}")
        elif name == "tbl":
            table += 1
            rows = [row for row in node if _word_name(row) == "tr"]
            for row_number, row in enumerate(rows, 1):
                cells = [cell for cell in row if _word_name(cell) == "tc"]
                for cell_number, cell in enumerate(cells, 1):
                    _blocks(
                        cell,
                        builder,
                        f"{prefix}table:{table}/row:{row_number}/cell:{cell_number}/",
                        depth + 1,
                    )
        else:
            # Content controls and custom-XML wrappers can contain ordinary blocks.
            # Include the wrapper's position so locators do not collide.
            _blocks(node, builder, f"{prefix}block:{index}/", depth + 1)


def _member(archive: zipfile.ZipFile, name: str, limits: DocumentLimits) -> bytes:
    with archive.open(name) as stream:
        data = stream.read(limits.max_unpacked_bytes + 1)
    if len(data) > limits.max_unpacked_bytes:
        fail("Word 内容展开后超过安全限制。")
    return data


def _validate_archive(archive: zipfile.ZipFile, limits: DocumentLimits):
    entries = archive.infolist()
    if len(entries) > limits.max_zip_entries:
        fail("Word 内部文件过多，请简化文件。")
    names = set()
    total = 0
    for entry in entries:
        path = PurePosixPath(entry.filename)
        if (
            entry.filename in names
            or path.is_absolute()
            or ".." in path.parts
            # ZipInfo normalizes Windows separators and truncates NULs. Inspect
            # the original spelling as well, before trusting normalized names.
            or "\\" in entry.orig_filename
            or "\x00" in entry.orig_filename
            or ":" in entry.filename
            or stat.S_ISLNK(entry.external_attr >> 16)
        ):
            fail("Word 内部路径或文件结构异常。")
        names.add(entry.filename)
        if entry.flag_bits & 1:
            fail("文件已加密，请去除密码后重新上传。")
        total += entry.file_size
        if total > limits.max_unpacked_bytes:
            fail("Word 内容展开后超过安全限制，请简化文件。")
        if entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            fail("Word 使用了不支持的压缩方式。")
    if not {"[Content_Types].xml", "_rels/.rels", "word/document.xml"} <= names:
        raise IntakeError("UNSUPPORTED_FILE_TYPE", "压缩包不是有效的 DOCX 文档。")
    if any(name.endswith("vbaProject.bin") for name in names):
        raise IntakeError("UNSUPPORTED_FILE_TYPE", "不支持含宏的 Word 文件。")
    # Validate every member, including images we do not interpret. Otherwise a
    # corrupt attachment could pass merely because the main XML was readable.
    expanded = 0
    for entry in entries:
        if entry.is_dir():
            continue
        with archive.open(entry) as stream:
            while True:
                chunk = stream.read(min(64 * 1024, limits.max_unpacked_bytes - expanded + 1))
                if not chunk:
                    break
                expanded += len(chunk)
                if expanded > limits.max_unpacked_bytes:
                    fail("Word 内容展开后超过安全限制，请简化文件。")


def _docx_pages(document, limits: DocumentLimits):
    explicit = 0
    rendered = 0
    pending = [document]
    while pending:
        node = pending.pop()
        name = _word_name(node)
        if name in {"del", "moveFrom"}:
            continue
        if name == "br" and _attribute(node, "type") == "page":
            explicit += 1
        if name == "lastRenderedPageBreak":
            rendered += 1
        pending.extend(node)
    # Cached app.xml page counts are not a reliable layout engine. Do not trust
    # them as proof that a DOCX meets the PDF's actual-page limit.
    if max(explicit, rendered) + 1 > limits.max_pages:
        fail("Word 中记录的分页超过限制，请缩减或另存为 PDF。")


def parse_docx(data: bytes, limits: DocumentLimits) -> ExtractedDocument:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        _validate_archive(archive, limits)
        content_types = _xml(_member(archive, "[Content_Types].xml", limits))
        if content_types.tag != f"{{{CONTENT_TYPES}}}Types" or not any(
            node.tag == f"{{{CONTENT_TYPES}}}Override"
            and node.get("PartName") == "/word/document.xml"
            and node.get("ContentType") == MAIN_DOCUMENT
            for node in content_types
        ):
            raise IntakeError("UNSUPPORTED_FILE_TYPE", "压缩包不是受支持的 DOCX 文档。")
        relationships = _xml(_member(archive, "_rels/.rels", limits))
        if not any(
            node.tag == f"{{{RELATIONSHIPS}}}Relationship"
            and (node.get("Type") or "").endswith("/officeDocument")
            and node.get("Target", "").lstrip("/") == "word/document.xml"
            and node.get("TargetMode") != "External"
            for node in relationships
        ):
            fail("Word 正文关系无效。")
        document = _xml(_member(archive, "word/document.xml", limits))
        if _word_name(document) != "document":
            fail("Word 正文结构无效。")
        body = next((node for node in document if _word_name(node) == "body"), None)
        if body is None:
            fail("Word 缺少正文。")
        _docx_pages(document, limits)
        builder = TextBuilder(limits)
        _blocks(body, builder)
        warnings = [DOCX_PAGINATION_WARNING]
        if any(
            _word_name(node) in {"del", "moveFrom", "ins", "moveTo"} for node in document.iter()
        ):
            warnings.append(
                "DOCX_TRACKED_CHANGES: 已忽略删除文字并保留插入文字，请核对修订后的内容。"
            )
        if any(
            name.startswith(("word/header", "word/footer", "word/footnotes", "word/endnotes"))
            for name in archive.namelist()
        ):
            warnings.append(
                "DOCX_AUXILIARY_TEXT_NOT_EXTRACTED: 本版读取正文和表格，页眉页脚及脚注尾注请另行核对。"
            )
        return builder.finish(warnings)
