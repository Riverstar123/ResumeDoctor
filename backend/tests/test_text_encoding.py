"""Exercise real UTF-8 files with Windows' legacy default encoding on any host."""

import io
import json

import pytest

from app.tools import check_contracts


@pytest.fixture
def legacy_default_encoding(monkeypatch):
    original = io.text_encoding

    def cp936_default(encoding, stacklevel=2):
        return "cp936" if encoding is None else original(encoding, stacklevel)

    monkeypatch.setattr(io, "text_encoding", cp936_default)
    # Prove that an implicit read actually exercises the reviewer's failure mode.
    with pytest.raises(UnicodeDecodeError):
        (check_contracts.REPO_ROOT / "docs/api/openapi.json").read_text()


def test_design_reads_utf8_with_legacy_default(legacy_default_encoding):
    expected = json.loads((check_contracts.REPO_ROOT / "docs/api/openapi.json").read_bytes())
    assert check_contracts.load_design() == expected


def test_checker_reads_utf8_examples_with_legacy_default(legacy_default_encoding, monkeypatch):
    # Isolate the checker's example reads so a broken design read cannot mask them.
    design = json.loads((check_contracts.REPO_ROOT / "docs/api/openapi.json").read_bytes())
    monkeypatch.setattr(check_contracts, "load_design", lambda root: design)
    result = check_contracts.run_checks()
    assert result["schemas"] == len(check_contracts.SCHEMA_MODELS)
    assert result["examples"] == len(check_contracts.EXAMPLES)
    assert not result["routes"]["pending"]
    assert "POST /session" in result["routes"]["implemented"]


@pytest.mark.parametrize("filename", check_contracts.EXAMPLES)
def test_fixture_reads_utf8_with_legacy_default(legacy_default_encoding, example, filename):
    expected = json.loads((check_contracts.REPO_ROOT / "docs/examples" / filename).read_bytes())
    assert example(filename) == expected
