"""Opt-in real old/new dependency conflicts; no network installation inside tests."""

import importlib.util
import json
import os
import shutil
import subprocess
import sysconfig
import venv
import zipfile
from pathlib import Path

import pytest

from tests.intake.document_fixtures import docx_bytes, pdf_bytes

BACKEND = Path(__file__).resolve().parents[2]
DEPENDENCIES = (
    "pypdf",
    "defusedxml",
    "pydantic",
    "pydantic_core",
    "annotated_types",
    "typing_extensions",
    "typing_inspection",
)


@pytest.fixture(scope="module", params=["flat", "split"])
def conflicting_runtime(tmp_path_factory, request):
    wheel = os.environ.get("RD_PARSER_OLD_PYPDF_WHEEL")
    if not wheel:
        pytest.skip("Set RD_PARSER_OLD_PYPDF_WHEEL to the official pypdf 3.17.4 wheel")
    root = tmp_path_factory.mktemp("conflicting parser dependencies")
    runtime = root / "runtime"
    venv.EnvBuilder(with_pip=False).create(runtime)
    python = runtime / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    site = Path(
        subprocess.check_output(
            [str(python), "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
            text=True,
        ).strip()
    )
    with zipfile.ZipFile(wheel) as archive:
        assert "Version: 3.17.4" in archive.read("pypdf-3.17.4.dist-info/METADATA").decode()
        archive.extractall(site)
    # Reuse other installed runtime packages after this interpreter's old pypdf.
    # Do not process the source environment's .pth files/editable app installation.
    (site / "runtime-fallback.pth").write_text(
        f"import sys; sys.path.append({ascii(sysconfig.get_path('purelib'))})\n",
        encoding="ascii",
    )
    roots = [root / "external first", root / "external second"]
    for directory in roots:
        directory.mkdir()
    for name in DEPENDENCIES:
        spec = importlib.util.find_spec(name)
        origin = Path(spec.origin).resolve()
        source = origin.parent if spec.submodule_search_locations else origin
        target = roots[1] if request.param == "split" and name == "pypdf" else roots[0]
        if source.is_dir():
            shutil.copytree(source, target / source.name)
        else:
            shutil.copy2(source, target / source.name)
    if request.param == "split":
        # pypdf is resolved from the later root. Resolving it first must not move
        # that directory ahead of the earlier root selected for defusedxml.
        shadow = roots[1] / "defusedxml"
        shadow.mkdir()
        (shadow / "__init__.py").write_text("raise RuntimeError('wrong root order')\n")
    else:
        roots = roots[:1]
    # External packages must never outrank standard-library modules or app code.
    for directory in roots:
        (directory / "colorsys.py").write_text("raise RuntimeError('stdlib shadowed')\n")
        (directory / "app").mkdir()
        (directory / "app/__init__.py").write_text("raise RuntimeError('app shadowed')\n")
    return root, python, roots


@pytest.mark.parametrize("kind", ["pdf", "docx"])
def test_real_parser_prefers_parent_dependencies_without_shadowing_stdlib(
    conflicting_runtime, kind
):
    root, python, dependencies = conflicting_runtime
    expected = "Synthetic resume example"
    document = root / f"synthetic.{kind}"
    document.write_bytes(
        pdf_bytes(expected)
        if kind == "pdf"
        else docx_bytes(f"<w:p><w:r><w:t>{expected}</w:t></w:r></w:p>")
    )
    # Probe executes the same trusted worker bootstrap in an isolated interpreter;
    # the actual DocumentExtractor call additionally checks the real parse path.
    probe = """import json,runpy,sys
worker,paths=sys.argv[1:]
sys.argv=[worker,'unused','{}',paths]
runpy.run_path(worker,run_name='dependency_probe')
import pypdf,defusedxml,colorsys,app
print(json.dumps({'version':pypdf.__version__,'pypdf':pypdf.__file__,
 'xml':defusedxml.__file__,'stdlib':colorsys.__file__,'app':app.__file__}))
"""
    driver = """import asyncio,io,json,subprocess,sys
from pathlib import Path
import pypdf
from app.intake.documents import DocumentExtractor,PDF,DOCX,_parser_dependency_paths
from app.intake import document_worker
data=Path(sys.argv[1]).read_bytes()
paths=_parser_dependency_paths()
probe=json.loads(subprocess.check_output([sys.executable,'-I','-X','utf8','-c',sys.argv[3],
 str(Path(document_worker.__file__).resolve()),json.dumps(paths)],text=True))
result=asyncio.run(DocumentExtractor().extract(io.BytesIO(data),PDF if sys.argv[2]=='pdf' else DOCX))
print(json.dumps({'text':result.text,'parent':pypdf.__version__,'paths':paths,'child':probe}))
"""
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(map(str, [BACKEND, *dependencies])))
    result = subprocess.run(
        [str(python), "-X", "utf8", "-c", driver, str(document), kind, probe],
        env=env,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    value = json.loads(result.stdout)
    assert value["text"] == expected
    assert value["parent"] == value["child"]["version"] == "6.21.0"
    assert value["paths"] == [str(path.resolve()) for path in dependencies]
    assert Path(value["child"]["pypdf"]).is_relative_to(dependencies[-1])
    assert Path(value["child"]["xml"]).is_relative_to(dependencies[0])
    assert not Path(value["child"]["stdlib"]).is_relative_to(root)
    assert Path(value["child"]["app"]).is_relative_to(BACKEND)
