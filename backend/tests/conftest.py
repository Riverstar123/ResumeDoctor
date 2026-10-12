import json

import pytest

from app.tools.check_contracts import REPO_ROOT, load_design


@pytest.fixture
def design():
    return load_design()


@pytest.fixture
def example():
    def load(name):
        return json.loads((REPO_ROOT / "docs/examples" / name).read_text(encoding="utf-8"))

    return load
