"""Generate disposable, explicitly synthetic files for the INT-02 browser route.

Run from backend: uv run --frozen python -m tests.platform.int02_fixtures --output /tmp/rd-demo
No original personal materials or binary fixtures are committed.
"""

import argparse
from pathlib import Path
from xml.sax.saxutils import escape

from app.platform.demo_gateway import JOB_TEXTS, PROFILE_TEXT
from tests.intake.document_fixtures import docx_bytes, pdf_bytes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    target = parser.parse_args().output
    target.mkdir(parents=True, exist_ok=True)
    paragraphs = PROFILE_TEXT.strip().splitlines()
    target.joinpath("synthetic-resume.pdf").write_bytes(pdf_bytes(*paragraphs))
    target.joinpath("synthetic-resume.docx").write_bytes(
        docx_bytes(
            "".join(f"<w:p><w:r><w:t>{escape(line)}</w:t></w:r></w:p>" for line in paragraphs)
        )
    )
    target.joinpath("source.txt").write_text(PROFILE_TEXT, encoding="utf-8")
    for index, text in enumerate(JOB_TEXTS, 1):
        target.joinpath(f"jd-{index}.txt").write_text(text, encoding="utf-8")
    print("Generated synthetic PDF, DOCX, source.txt and five JD texts.")


if __name__ == "__main__":
    main()
