"""Private stdin/stdout worker. It never opens paths found in uploaded content."""

import json
import sys
from dataclasses import asdict

from .document_parser import parse_document
from .documents import DocumentLimits
from .errors import IntakeError


def main():
    try:
        limits = DocumentLimits(**json.loads(sys.argv[2]))
        data = sys.stdin.buffer.read(limits.max_file_bytes + 1)
        document = parse_document(data, sys.argv[1], limits)
        result = {"ok": True, **asdict(document)}
    except IntakeError as exc:
        result = {"ok": False, "code": exc.code, "message": str(exc)}
    except Exception:
        # Never put parser exceptions, paths, original text or XML into responses/logs.
        result = {
            "ok": False,
            "code": "DOCUMENT_PARSE_FAILED",
            "message": "文件损坏、加密或内容无法解析，请更换文件或使用对话输入。",
        }
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
