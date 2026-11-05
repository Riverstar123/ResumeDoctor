"""Opt-in deployed-ZIP regression; requires a separate runtime-only Python environment."""

import json
import os
import subprocess
import venv
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from app.platform.demo_gateway import PROFILE_TEXT
from tests.intake.document_fixtures import docx_bytes, pdf_bytes

ROOT = Path(__file__).resolve().parents[3]
PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture(scope="module", params=["venv", "external-dependencies"])
def release(tmp_path_factory, request):
    archive = os.environ.get("RD_SHOW_ARCHIVE_ZIP")
    python = os.environ.get("RD_SHOW_ARCHIVE_PYTHON")
    if not archive or not python:
        pytest.skip("Set RD_SHOW_ARCHIVE_ZIP and RD_SHOW_ARCHIVE_PYTHON (fresh runtime-only venv)")
    assert Path(archive).is_file() and Path(python).is_file()
    root = tmp_path_factory.mktemp("unpacked release with spaces")
    with zipfile.ZipFile(archive) as packed:
        assert packed.testzip() is None
        assert "backend/.env" not in packed.namelist()
        packed.extractall(root)
    dependencies = []
    if request.param == "external-dependencies":
        # Match hosts using pip --target/PYTHONPATH: the selected interpreter has
        # no packages, and -I grandchildren cannot rely on inherited PYTHONPATH.
        dependencies = json.loads(
            subprocess.check_output(
                [
                    python,
                    "-I",
                    "-c",
                    "import json,sysconfig;print(json.dumps([sysconfig.get_path('purelib'),sysconfig.get_path('platlib')]))",
                ],
                text=True,
            )
        )
        isolated = tmp_path_factory.mktemp("bare interpreter")
        venv.EnvBuilder(with_pip=False).create(isolated)
        python = str(isolated / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
    return root, python, dependencies


@pytest.mark.parametrize(
    "kind,valid", [("pdf", True), ("docx", True), ("pdf", False), ("docx", False)]
)
def test_unpacked_release_document_to_profile_with_independent_worker(
    release, tmp_path, kind, valid
):
    root, python, dependencies = release
    if kind == "pdf":
        data = pdf_bytes(*PROFILE_TEXT.strip().splitlines()) if valid else b"%PDF-1.7\ncorrupt"
    else:
        body = "".join(
            f"<w:p><w:r><w:t>{escape(line)}</w:t></w:r></w:p>"
            for line in PROFILE_TEXT.strip().splitlines()
        )
        data = docx_bytes(body if valid else "<w:p>")
    document = tmp_path / f"synthetic-{'valid' if valid else 'corrupt'}.{kind}"
    document.write_bytes(data)
    env = {key: value for key, value in os.environ.items() if not key.startswith("LLM_")}
    env.update(
        DATA_DIR=str(tmp_path / "data"),
        LLM_MODE="fake",
        LLM_PROVIDER="fake",
        SESSION_COOKIE_SECURE="false",
        SHOW_ORIGIN="http://archive.test",
        PYTHONPATH=str(root / "backend"),
    )
    result = subprocess.run(
        [
            python,
            "-I",
            "-X",
            "utf8",
            str(ROOT / "backend/tests/e2e/show_archive.py"),
            "--release",
            str(root),
            "--document",
            str(document),
            "--media-type",
            PDF if kind == "pdf" else DOCX,
            "--expected-status",
            "succeeded" if valid else "failed",
            *[argument for path in dependencies for argument in ("--dependency-dir", path)],
        ],
        cwd=root,
        env=env,
        capture_output=True,
        timeout=45,
    )
    assert result.returncode == 0, (result.stdout + result.stderr).decode("utf-8", errors="replace")
