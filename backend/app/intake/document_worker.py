"""Private stdin/stdout worker. It never opens paths found in uploaded content."""

import json
import sys
import sysconfig
from dataclasses import asdict
from pathlib import Path


def _configure_import_paths(dependencies: list[str]) -> None:
    """Application/stdlib first, selected dependencies next, interpreter packages last."""
    # Exact interpreter-owned roots, not a prefix match: site-packages itself
    # usually lives beneath stdlib. Keep zip and extension-module roots too.
    standard = {Path(sysconfig.get_path(name)).resolve() for name in ("stdlib", "platstdlib")}
    for directory in tuple(standard):
        standard.add(directory / "lib-dynload")
        standard.add(
            directory.parent / f"python{sys.version_info.major}{sys.version_info.minor}.zip"
        )
    standard.update(
        Path(prefix).resolve() / "DLLs" for prefix in (sys.base_prefix, sys.base_exec_prefix)
    )
    if shared := sysconfig.get_config_var("DESTSHARED"):
        standard.add(Path(shared).resolve())
    library = [path for path in sys.path if Path(path).resolve() in standard]
    remaining = [path for path in sys.path if Path(path).resolve() not in standard]
    sys.path[:] = list(
        dict.fromkeys(
            [
                str(Path(__file__).resolve().parents[2]),
                *library,
                *dependencies,
                *remaining,
            ]
        )
    )


# -I ignores cwd/PYTHONPATH. Only the owning backend and dependency roots resolved
# by the parent are added; none of these paths comes from uploaded content.
if __package__ in {None, ""}:
    _configure_import_paths(json.loads(sys.argv[3]))

from app.intake.document_parser import parse_document  # noqa: E402
from app.intake.documents import DocumentLimits  # noqa: E402
from app.intake.errors import IntakeError  # noqa: E402


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
