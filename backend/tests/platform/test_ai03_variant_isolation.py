"""PR #60 复审 P2：AI-03 success/degrade 变体的队列隔离回归。

real 模式 Playwright 会让两套 API/worker 同时存活：变体间上传目录与模型
映射不同（degrade 还覆盖 LLM_MODEL_A），若共用同一个任务队列，worker 可能
领走另一变体的任务——上传目录不匹配使任务 failed/INTERNAL_ERROR，或坏模型
映射在保存评分前就失败，拿不到预期 score_only。修复按变体使用独立 test 库。

本测试用与正式启动器相同的一次性集群设施（tests.e2e.cluster）起两个已迁移
数据库，经生产入口 create_worker 构造两个 worker，断言它们同时存活时互不
认领对方任务、只处理各自队列。需要便携 PostgreSQL（RD_AI03_PG_HOME 或
RD_QA03_PG_HOME）；全部输入合成，不触网、不调供应商。
"""

import asyncio
import os
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")
from sqlalchemy import create_engine, text  # noqa: E402

from app.platform.repositories import PostgreSQLRepository  # noqa: E402
from app.settings import Settings  # noqa: E402
from tests.e2e.cluster import ensure_cluster, ensure_database  # noqa: E402

SUCCESS_DB = "rd_ai03_iso_success_test"
DEGRADE_DB = "rd_ai03_iso_degrade_test"


def _default_runtime_root() -> Path:
    """跨平台集群根：显式覆盖或系统临时目录。

    不直接读 ``os.environ["TEMP"]``：macOS/Linux 通常只有 TMPDIR 或使用系统
    默认值，``tempfile.gettempdir()`` 覆盖全部约定（PR #60 第三轮复审 P2）。
    """
    override = os.environ.get("RD_AI03_ISOLATION_ROOT")
    if override:
        return Path(override)
    return Path(tempfile.gettempdir()) / "rd-ai03-isolation"


def _ascii_runtime_root() -> Path:
    root = _default_runtime_root()
    # postgres -k 经命令行接收非 ASCII 路径会按系统代码页乱码并 FATAL。
    if any(ord(ch) > 127 for ch in str(root)):
        pytest.skip(
            f"临时根含非 ASCII 字符（{root}）；请设置 RD_AI03_ISOLATION_ROOT 指向 ASCII 路径"
        )
    return root


@pytest.fixture(scope="module")
def databases(tmp_path_factory):
    pg_home = os.environ.get("RD_AI03_PG_HOME", os.environ.get("RD_QA03_PG_HOME"))
    if not pg_home:
        pytest.skip("队列隔离回归需要 RD_AI03_PG_HOME / RD_QA03_PG_HOME 指向便携 PostgreSQL")
    # 集群根必须是 ASCII 且不依赖 TEMP：默认系统临时目录，可用
    # RD_AI03_ISOLATION_ROOT 覆盖（postgres -k 不支持非 ASCII 路径）。
    runtime = _ascii_runtime_root()
    host, port = ensure_cluster(Path(pg_home), runtime / "cluster")
    success_url = ensure_database(host, port, SUCCESS_DB)
    degrade_url = ensure_database(host, port, DEGRADE_DB)
    uploads_root = tmp_path_factory.mktemp("ai03-isolation-uploads")
    engines = create_engine(success_url), create_engine(degrade_url)
    yield success_url, degrade_url, engines, uploads_root
    for engine in engines:
        engine.dispose()


def _enqueue(repository, sid, worker):
    # 与 test_jobs.enqueue_worker_job 相同：经 DatabasePlatform 入队，冻结快照
    # 由 worker 自己的目录生成（model_id/provider/model/版本均一致），避免手工
    # 快照与目录解析不一致导致 MODEL_UNAVAILABLE。
    from app.contracts import JobCreate
    from app.intake import SYNTHETIC_JOB_RAW_TEXT
    from app.platform.database_service import DatabasePlatform

    platform = DatabasePlatform(repository, worker.catalog, worker.upload_dir)
    accepted = platform.job_create(
        sid,
        JobCreate(raw_text=SYNTHETIC_JOB_RAW_TEXT, company_context="", model_id="demo-model-a"),
        uuid4().hex,
    )
    return accepted.task_id


def _worker(url, upload_dir, repository):
    from app.platform.jobs.worker import create_worker

    settings = Settings(
        _env_file=None,
        database_url=url,
        upload_dir=str(upload_dir),
        allowed_origins=["http://127.0.0.1:0"],
        llm_mode="fake",
        llm_provider="fake",
    )
    return create_worker(settings, repository=repository)


def _status(engine, task_id):
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT status FROM tasks WHERE id = :id"), {"id": task_id}
        ).scalar_one()


def test_two_variant_workers_do_not_cross_claim(databases):
    success_url, degrade_url, (engine_success, engine_degrade), uploads_root = databases
    repo_success = PostgreSQLRepository(engine_success)
    repo_degrade = PostgreSQLRepository(engine_degrade)
    sid_success = repo_success.create_session()[0].public.id
    sid_degrade = repo_degrade.create_session()[0].public.id

    upload_success = uploads_root / "success"
    upload_degrade = uploads_root / "degrade"
    upload_success.mkdir(parents=True, exist_ok=True)
    upload_degrade.mkdir(parents=True, exist_ok=True)
    # worker 先于入队：冻结快照由 worker 自己的目录生成。
    worker_success = _worker(success_url, upload_success, repo_success)
    worker_degrade = _worker(degrade_url, upload_degrade, repo_degrade)

    # 先只往 success 队列排任务。
    task_success = _enqueue(repo_success, sid_success, worker_success)

    try:
        # degrade worker 看不见 success 队列：空转返回 False，任务仍 queued。
        assert asyncio.run(worker_degrade.run_once()) is False
        assert _status(engine_success, task_success) == "queued"

        # success worker 只处理自己的任务。
        assert asyncio.run(worker_success.run_once()) is True
        assert _status(engine_success, task_success) == "succeeded"

        # 现在才往 degrade 队列排任务。
        task_degrade = _enqueue(repo_degrade, sid_degrade, worker_degrade)

        # 反向同样隔离：success worker 空转，degrade 任务仍 queued。
        assert asyncio.run(worker_success.run_once()) is False
        assert _status(engine_degrade, task_degrade) == "queued"

        # degrade worker 处理自己的任务。
        assert asyncio.run(worker_degrade.run_once()) is True
        assert _status(engine_degrade, task_degrade) == "succeeded"
    finally:
        repo_success.revoke(sid_success)
        repo_degrade.revoke(sid_degrade)


def test_runtime_root_defaults_when_temp_is_unset(monkeypatch, tmp_path):
    # macOS/Linux 典型环境：TEMP/TMP/TMPDIR 全部缺失，也没有覆盖变量。
    for name in ("TEMP", "TMP", "TMPDIR", "RD_AI03_ISOLATION_ROOT"):
        monkeypatch.delenv(name, raising=False)
    # gettempdir() 会缓存首次解析结果；把缓存钉到 ASCII 临时目录上。
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    assert _default_runtime_root() == tmp_path / "rd-ai03-isolation"


def test_runtime_root_uses_documented_override(monkeypatch, tmp_path):
    override = tmp_path / "custom-root"
    monkeypatch.setenv("RD_AI03_ISOLATION_ROOT", str(override))
    assert _default_runtime_root() == override


def test_non_ascii_runtime_root_is_skipped_with_override_hint(monkeypatch):
    monkeypatch.setenv("RD_AI03_ISOLATION_ROOT", r"C:\Users\黛芬\rd-root")
    with pytest.raises(pytest.skip.Exception, match="RD_AI03_ISOLATION_ROOT"):
        _ascii_runtime_root()
