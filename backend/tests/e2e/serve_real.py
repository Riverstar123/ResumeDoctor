"""QA-03 正式栈变体启动器：app.database + 独立 worker 进程 + 临时 PostgreSQL。

用法（backend/ 下）：

    python -m tests.e2e.serve_real --variant success --port 8020 \
        --origin http://127.0.0.1:5190 --pg-home C:\\rd\\pgsql

启动器负责：确保/复用本地一次性 PostgreSQL 集群、创建并迁移名称含 test 的
变体数据库、用相同环境拉起独立 worker 进程（python -m tests.e2e.worker_real）、
挂载仅测试用的控制面（/api/e2e/*，不经 /api/v1 守卫、不随生产代码发布），
最后在进程内运行真实 uvicorn + app.database.create_app。业务代码没有任何
test-only 分支；失败只来自服务端环境，同步点只来自本地环回控制面。
"""

import argparse
import atexit
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import uvicorn
from fastapi import APIRouter, Response
from sqlalchemy import create_engine, text

from app.database import create_app as create_database_app
from app.llm import FakeModelDirectory
from app.settings import Settings

from .cluster import ensure_cluster, ensure_database, stop_cluster
from .real_harness import REAL_VARIANTS, gateway_from_env

BACKEND_DIR = Path(__file__).resolve().parents[2]

_e2e_router = APIRouter(prefix="/api/e2e", tags=["qa03-control"])

COUNT_TABLES = (
    "profiles",
    "profile_versions",
    "jobs",
    "job_versions",
    "tasks",
    "diagnoses",
    "diagnosis_items",
    "idempotency_keys",
    "messages",
    "documents",
)


def _read_events(sync_dir: Path, limit: int = 20) -> list[dict]:
    log = sync_dir / "worker.log"
    if not log.exists():
        return []
    lines = log.read_text(encoding="utf-8").splitlines()
    events = []
    for line in lines[-limit:]:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def install_control_router(app, engine, sync_dir: Path) -> None:
    @_e2e_router.get("/state")
    def state(token: str, sid: str | None = None):
        """token 用于解析当前会话；撤销后 worker 清理会物理删除会话行，
        因此浏览器用例在撤销前记录 sid，并在撤销后用 sid 显式复核各表零残留。"""
        if not sid:
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT id::text, revoked_at IS NOT NULL FROM sessions WHERE token_hash = :h"
                    ),
                    {"h": token_hash},
                ).first()
            sid, revoked = (row[0], row[1]) if row else (None, True)
        else:
            revoked = True
        with engine.connect() as conn:
            counts = {}
            if sid:
                for table in COUNT_TABLES:
                    counts[table] = conn.execute(
                        text(f"SELECT count(*) FROM {table} WHERE session_id = :sid"),
                        {"sid": sid},
                    ).scalar()
        return {
            "session_id": sid,
            "revoked": bool(revoked),
            "counts": counts,
            "blocked": (sync_dir / "blocked.json").exists(),
            "released": (sync_dir / "release").exists(),
            "events": _read_events(sync_dir),
        }

    @_e2e_router.post("/release", status_code=204)
    def release():
        sync_dir.mkdir(parents=True, exist_ok=True)
        (sync_dir / "release").write_text("", encoding="utf-8")
        return Response(status_code=204)

    app.include_router(_e2e_router)


def _worker_env(url: str, uploads: Path, origin: str, variant: str, sync_dir: Path) -> dict:
    env = dict(os.environ)
    env.update(
        {
            "DATABASE_URL": url,
            "UPLOAD_DIR": str(uploads),
            "ALLOWED_ORIGINS": json.dumps([origin]),
            "LLM_MODE": "fake",
            "PYTHONUNBUFFERED": "1",
        }
    )
    env["RD_E2E_SYNC_DIR"] = str(sync_dir)
    env.update(REAL_VARIANTS[variant])
    return env


def _reset_sync_dir(sync_dir: Path) -> None:
    sync_dir.mkdir(parents=True, exist_ok=True)
    for name in ("blocked.json", "released.json", "release", "worker.log"):
        target = sync_dir / name
        if target.exists():
            target.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=sorted(REAL_VARIANTS))
    parser.add_argument("--port", type=int)
    parser.add_argument("--origin")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--pg-home", default=os.environ.get("RD_QA03_PG_HOME"))
    parser.add_argument("--runtime-root", default=os.environ.get("RD_QA03_RUNTIME_ROOT"))
    parser.add_argument("--stop-cluster", action="store_true", help="停止共享集群后退出")
    args = parser.parse_args()

    if not args.pg_home:
        parser.error("需要 --pg-home 或 RD_QA03_PG_HOME 指向便携 PostgreSQL 的 pgsql 目录")
    root = (
        Path(args.runtime_root)
        if args.runtime_root
        else Path(os.environ.get("TEMP", "/tmp")) / "rd-qa03"
    )
    if args.stop_cluster:
        stop_cluster(args.pg_home, root / "cluster")
        return
    missing = [
        name
        for name, value in (
            ("--variant", args.variant),
            ("--port", args.port),
            ("--origin", args.origin),
        )
        if value is None
    ]
    if missing:
        parser.error(f"缺少运行必需参数：{' '.join(missing)}")
        return

    host, pg_port = ensure_cluster(Path(args.pg_home), root / "cluster")
    db_name = f"rd_qa03_{args.variant}_test"
    url = ensure_database(host, pg_port, db_name)

    variant_root = root / args.variant
    uploads = variant_root / "uploads"
    sync_dir = variant_root / "sync"
    uploads.mkdir(parents=True, exist_ok=True)
    _reset_sync_dir(sync_dir)

    # 让本进程的 Settings 与网关同样读取变体环境（API 进程本身不执行模型任务）。
    os.environ.update(_worker_env(url, uploads, args.origin, args.variant, sync_dir))
    worker = subprocess.Popen(
        [sys.executable, "-u", "-m", "tests.e2e.worker_real"],
        cwd=BACKEND_DIR,
        env=dict(os.environ),
        stdout=(root / args.variant / "worker.stdout.log").open("ab"),
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    atexit.register(lambda: worker.poll() is None and worker.terminate())

    settings = Settings(
        _env_file=None,
        database_url=url,
        upload_dir=uploads,
        allowed_origins=[args.origin],
        llm_mode="fake",
    )
    gateway = gateway_from_env(FakeModelDirectory())
    app = create_database_app(settings, gateway=gateway)
    app.title = "ResumeDoctor QA-03 real stack / PostgreSQL, worker, business modules"
    install_control_router(app, create_engine(url, pool_size=5), sync_dir)

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
