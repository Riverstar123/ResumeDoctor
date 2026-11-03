"""Display entry configuration, same-origin routing and supervisor lifecycle."""

# ruff: noqa: E402 -- SQLAlchemy is optional outside persistent assemblies.

import importlib.util
import os
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from app.platform.repositories.sqlite import initialize_sqlite
from app.show import create_app, show_settings

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_MODE", "fake")
    monkeypatch.setenv("SHOW_ORIGIN", "http://localhost:8841")
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "false")
    value = show_settings()
    initialize_sqlite(value.database_url.get_secret_value())
    return value


def test_display_entry_ignores_local_database_and_disables_optional_models(settings, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unusable-local-database")
    monkeypatch.setenv("LLM_MODEL_B", "configured-but-disabled")
    monkeypatch.setenv("LLM_API_KEY_B", "synthetic-not-a-provider-credential")
    value = show_settings()
    assert value.database_url.get_secret_value() == settings.database_url.get_secret_value()
    assert value.llm_model_b == "" and value.llm_api_key_b.get_secret_value() == ""
    assert value.llm_model_a == "" and not value.session_cookie_secure
    monkeypatch.setenv("DATA_DIR", "relative-data")
    with pytest.raises(ValueError, match="absolute"):
        show_settings()


def test_real_display_catalog_has_only_deepseek_and_fails_without_key(settings, monkeypatch):
    from app.llm import GatewayError, build_llm

    monkeypatch.setenv("LLM_MODE", "real")
    monkeypatch.setenv("LLM_MODEL", "synthetic-configured-model")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("LLM_API_KEY", "synthetic-configuration-only")
    monkeypatch.setenv("LLM_MODEL_B", "disabled-glm")
    value = show_settings()
    directory = build_llm(value).directory
    assert [model.id for model in directory.list_models().items] == ["real-default"]
    monkeypatch.delenv("LLM_API_KEY")
    with pytest.raises(GatewayError):
        build_llm(show_settings())


def test_deployment_requirements_match_locked_runtime_dependencies():
    project = tomllib.loads((ROOT / "backend/pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    expected = set(project["dependencies"] + project["optional-dependencies"]["sqlite"])
    actual = {
        line.strip()
        for line in (ROOT / "requirements.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert actual == expected


@pytest.fixture
def public_dist(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>public frontend</html>", encoding="utf-8")
    (dist / "assets/app.js").write_text("console.log('public');", encoding="utf-8")
    secret = tmp_path / "private.txt"
    secret.write_text("private-test-content", encoding="utf-8")
    return dist


def test_static_spa_refresh_api_and_private_paths_are_separate(settings, public_dist):
    dist = public_dist
    with TestClient(create_app(settings, dist=dist)) as client:
        for route in ("/", "/jobs", "/history", "/profiles/synthetic", "/diagnoses/synthetic"):
            assert client.get(route).text == "<html>public frontend</html>"
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/assets/app.js").status_code == 200
        for route in (
            "/backend/.env",
            "/resumedoctor.sqlite3",
            "/assets/missing.js",
            "/api/missing",
            "/%2e%2e/private.txt",
            "/assets/%2e%2e/%2e%2e/private.txt",
        ):
            response = client.get(route)
            assert response.status_code == 404
            assert "private-test-content" not in response.text
        assert client.get("/api/v1/profiles/unknown").status_code == 401


@pytest.mark.parametrize("path", ["private-link.txt", "assets/private-link.txt"])
def test_static_symlink_escape_is_rejected_when_supported(settings, public_dist, path):
    try:
        (public_dist / path).symlink_to(public_dist.parent / "private.txt")
    except (OSError, NotImplementedError):
        pytest.skip(
            "Symbolic links unavailable; on Windows enable Developer Mode or run with "
            "symlink privileges to cover this path. Other static isolation tests still run."
        )
    with TestClient(create_app(settings, dist=public_dist)) as client:
        response = client.get(f"/{path}")
        assert response.status_code == 404
        assert "private-test-content" not in response.text


def test_archive_whitelist_excludes_local_credentials_and_runtime(tmp_path):
    spec = importlib.util.spec_from_file_location("package_show", ROOT / "scripts/package_show.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = tmp_path
    names = (
        "deploy.json",
        "requirements.txt",
        "scripts/run_show.py",
        "backend/app/example.py",
        "backend/config/models.yaml",
        "frontend/dist/index.html",
        "frontend/dist/assets/app.js",
        "backend/.env",
        "frontend/.env",
        "uploads/private.txt",
        "output/private.txt",
        "backend/app/__pycache__/example.pyc",
        "backend/tests/private.py",
        "frontend/dist/.env",
    )
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic fixture", encoding="utf-8")
    output = tmp_path / "archive.zip"
    module.package(output, build=False)
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == set(names[:7])
    (tmp_path / "backend/app/example.py").write_text("sk-" + "a" * 24, encoding="utf-8")
    with pytest.raises(ValueError, match="credential"):
        module.package(tmp_path / "rejected.zip", build=False)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal/process supervision acceptance")
def test_supervisor_child_failure_terminates_sibling(settings, tmp_path):
    # Replace child executables only, while exercising the real provisioning and
    # supervision code. No listening socket or external model is needed here.
    script = tmp_path / "supervisor_acceptance.py"
    marker = tmp_path / "worker.pid"
    script.write_text(
        "import importlib.util,sys\n"
        f"spec=importlib.util.spec_from_file_location('run_show',{str(ROOT / 'scripts/run_show.py')!r})\n"
        "module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)\n"
        "original=module.subprocess.Popen\n"
        "def spawn(command,**kwargs):\n"
        "    if command[2]=='app.platform.jobs':\n"
        f'        code="import os,time;from pathlib import Path;Path({str(marker)!r}).write_text(str(os.getpid()));time.sleep(60)"\n'
        "    else:\n"
        "        code='import time;time.sleep(0.5);raise SystemExit(7)'\n"
        "    return original([sys.executable,'-c',code],**kwargs)\n"
        "module.subprocess.Popen=spawn\n"
        "raise SystemExit(module.main())\n",
        encoding="utf-8",
    )
    process = subprocess.run([sys.executable, str(script)], timeout=20, capture_output=True)
    assert process.returncode == 1, process.stderr.decode()
    assert marker.is_file()
    with pytest.raises(ProcessLookupError):
        os.kill(int(marker.read_text()), 0)
