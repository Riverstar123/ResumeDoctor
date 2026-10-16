"""Bounded document extraction; borrowed streams stay owned by the caller.

Untrusted parsing runs in a disposable process. No files are uploaded, saved,
or deleted here. M2 owns original files, source IDs, persistence and HTTP errors.
"""

import asyncio
import json
import math
import sys
from contextlib import suppress
from dataclasses import asdict, dataclass
from typing import BinaryIO

from app.contracts import ProfileContent
from app.contracts.ports import ExtractedDocument, TextSegment

from .errors import IntakeError

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@dataclass(frozen=True)
class DocumentLimits:
    """Server-controlled budgets, never populated from an uploaded document."""

    max_file_bytes: int = 10 * 1024 * 1024
    max_pages: int = 20
    max_unpacked_bytes: int = 10 * 1024 * 1024
    max_zip_entries: int = 1024
    max_text_chars: int = 30_000
    max_segments: int = 5000
    timeout_seconds: float = 10.0

    def __post_init__(self):
        for key, value in asdict(self).items():
            if key == "timeout_seconds":
                if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                    raise ValueError("timeout_seconds must be finite and positive")
            elif type(value) is not int or value <= 0:
                raise ValueError(f"{key} must be a positive integer")


def _read_document(handle: BinaryIO, maximum: int) -> bytes:
    position = None
    try:
        if handle.seekable():
            position = handle.tell()
            handle.seek(0)
        chunks = []
        size = 0
        while size <= maximum:
            part = handle.read(min(64 * 1024, maximum + 1 - size))
            if not isinstance(part, bytes):
                raise TypeError("a binary stream is required")
            if not part:
                break
            chunks.append(part)
            size += len(part)
        if size > maximum:
            raise IntakeError("FILE_TOO_LARGE", "文件超过大小限制，请缩减后重试。")
        if size == 0:
            raise IntakeError("DOCUMENT_PARSE_FAILED", "文件为空，请重新选择文件。")
        return b"".join(chunks)
    except IntakeError:
        raise
    except (AttributeError, OSError, TypeError, ValueError):
        raise IntakeError("DOCUMENT_PARSE_FAILED", "无法读取文件，请重新上传。") from None
    finally:
        if position is not None:
            with suppress(OSError, ValueError):
                handle.seek(position)


class DocumentExtractor:
    def __init__(self, limits: DocumentLimits | None = None):
        self.limits = limits or DocumentLimits()

    async def extract(self, handle: BinaryIO, media_type: str) -> ExtractedDocument:
        if media_type not in (PDF, DOCX):
            raise IntakeError("UNSUPPORTED_FILE_TYPE", "仅支持文字 PDF 和 DOCX 文件。")
        data = _read_document(handle, self.limits.max_file_bytes)
        process = None
        communication = None
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-I",
                "-X",
                "utf8",
                "-m",
                "app.intake.document_worker",
                media_type,
                json.dumps(asdict(self.limits)),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                # Parser warnings can quote document content. Never forward them to logs.
                stderr=asyncio.subprocess.DEVNULL,
            )
            communication = asyncio.create_task(process.communicate(data))
            output, _ = await asyncio.wait_for(
                asyncio.shield(communication), self.limits.timeout_seconds
            )
            if process.returncode != 0:
                raise ValueError("document worker failed")
            return self._decode(output)
        except TimeoutError:
            raise IntakeError(
                "DOCUMENT_PARSE_FAILED", "文件解析超时，请简化文件或改用对话输入。"
            ) from None
        except IntakeError:
            raise
        except (OSError, NotImplementedError, ValueError, KeyError, TypeError):
            raise IntakeError(
                "DOCUMENT_PARSE_FAILED", "无法解析文件，请更换文件或改用对话输入。"
            ) from None
        finally:
            # This also runs when the caller cancels the task. No abandoned parser remains.
            if process is not None:
                if process.returncode is None:
                    with suppress(ProcessLookupError):
                        process.kill()
                if communication is not None:
                    await asyncio.gather(communication, return_exceptions=True)
                else:
                    await process.wait()

    def _decode(self, output: bytes) -> ExtractedDocument:
        if len(output) > self.limits.max_text_chars * 8 + self.limits.max_segments * 256:
            raise ValueError("oversized worker response")
        result = json.loads(output)
        if not isinstance(result, dict):
            raise ValueError("invalid worker response")
        if result.get("ok") is False:
            code = result["code"]
            if code not in {
                "FILE_TOO_LARGE",
                "UNSUPPORTED_FILE_TYPE",
                "DOCUMENT_PARSE_FAILED",
                "NO_TEXT_LAYER",
                "INPUT_TOO_LONG",
            }:
                raise ValueError("unknown worker error")
            raise IntakeError(code, result["message"])
        if result.get("ok") is not True:
            raise ValueError("invalid worker response")
        text = result["text"]
        segments = tuple(TextSegment(**item) for item in result["segments"])
        warnings = tuple(result["warnings"])
        if (
            not isinstance(text, str)
            or not text.strip()
            or len(text) > self.limits.max_text_chars
            or not segments
            or len(segments) > self.limits.max_segments
            or any(not isinstance(s.text, str) or s.text not in text for s in segments)
            or any(not isinstance(s.locator, str) for s in segments)
            or any(not isinstance(w, str) for w in warnings)
        ):
            raise ValueError("invalid extracted document")
        return ExtractedDocument(text=text, segments=segments, warnings=warnings)


def locate_document_evidence(
    profile: ProfileContent, document: ExtractedDocument, source_id: str
) -> ProfileContent:
    """Attach locations derived from source text, never from a model's guess.

    The caller must pass the source ID used for this document's build_profile call.
    Cross-segment or ambiguous quotes deliberately retain a null locator.
    """
    located = profile.model_copy(deep=True)
    for evidence in located.evidence:
        if evidence.source_type != "document" or evidence.source_id != source_id:
            continue
        if evidence.quote not in document.text:
            raise IntakeError("QUOTE_NOT_IN_SOURCE", "引用内容不存在于文件提取的原文中。")
        matches = [
            segment.locator for segment in document.segments if evidence.quote in segment.text
        ]
        evidence.locator = matches[0] if len(matches) == 1 else None
    return located
