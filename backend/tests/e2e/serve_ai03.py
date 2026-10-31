"""AI-03 真实模型验收启动器：生产装配 + 独立 worker + 一次性 PostgreSQL。

与 QA-03 的 serve_real 区别：不挂测试控制面、不替换网关、不强制 fake。
API 走生产入口 ``app.database.create_app``，worker 走生产入口
``python -m app.platform.jobs``，二者共用同一组环境与（real 模式）组长本地
填写的 ``backend/.env``。

- 默认 ``--llm-mode fake``：用于开发调试，合成资料 + fake 网关，不发任何
  外部请求；
- ``--llm-mode real``：只在 AI-03 显式真实验收时使用，从 backend/.env 读取
  LLM_BASE_URL / LLM_MODEL / LLM_API_KEY / LLM_MODEL_A / LLM_MODEL_B；
- ``--bad-model-a``：仅 real 可用，把 LLM_MODEL_A 在本进程覆盖为一个不存在
  的模型名，制造一次**真实供应商返回的配置错误**，验证报告失败后岗位降级
  为 score_only（不是服务端 fake 注入）。

每个验收变体使用各自名称含 test 的独立数据库（success 为 rd_ai03_success_test，
degrade 为 rd_ai03_degrade_test）：两套 API/worker 同时存活时队列物理隔离，
不会互领上传目录或模型映射不同的任务（PR #60 复审 P2）。启动器负责集群就绪、
建库与迁移。

用法（backend/ 下）：

    python -m tests.e2e.serve_ai03 --port 8030 \\
        --origin http://127.0.0.1:5200 --pg-home C:\\rd-qa03-pg\\pgsql \\
        --llm-mode real
"""

import argparse
import atexit
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import uvicorn

from app.database import create_app as create_database_app
from app.settings import load_settings

from .cluster import ensure_cluster, ensure_database

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_NAME = "rd_ai03_success_test"
# 库名只接受启动器固定风格（小写字母/下划线，且含 test），不接受任意外部输入。
_DATABASE_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")
# 明显不存在的模型名：触发供应商 4xx，证明真实降级链路；不会误命中真实模型。
BAD_MODEL_NAME = "ai03-nonexistent-model-zzz"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--pg-home",
        default=os.environ.get("RD_AI03_PG_HOME", os.environ.get("RD_QA03_PG_HOME")),
    )
    parser.add_argument("--runtime-root", default=os.environ.get("RD_AI03_RUNTIME_ROOT"))
    parser.add_argument("--llm-mode", choices=("fake", "real"), default="fake")
    parser.add_argument("--bad-model-a", action="store_true")
    parser.add_argument("--uploads-name", default="uploads")
    parser.add_argument(
        "--db-name",
        default=DEFAULT_DATABASE_NAME,
        help="本变体专用 test 数据库（success/degrade 必须不同，默认 rd_ai03_success_test）",
    )
    args = parser.parse_args()

    if not args.pg_home:
        parser.error("需要 --pg-home 或 RD_AI03_PG_HOME / RD_QA03_PG_HOME 指向便携 PostgreSQL")
    if args.bad_model_a and args.llm_mode != "real":
        parser.error("--bad-model-a 只能配合 --llm-mode real")
    if not _DATABASE_NAME.fullmatch(args.db_name) or "test" not in args.db_name:
        parser.error(f"非法 --db-name：{args.db_name}")
    root = (
        Path(args.runtime_root)
        if args.runtime_root
        else Path(os.environ.get("TEMP", "/tmp")) / "rd-ai03"
    )

    host, pg_port = ensure_cluster(Path(args.pg_home), root / "cluster")
    url = ensure_database(host, pg_port, args.db_name)
    uploads = root / args.uploads_name
    uploads.mkdir(parents=True, exist_ok=True)

    # 环境变量优先级高于 .env：集群 URL/上传目录/Origin 由启动器固定，
    # real 模式的 LLM_* 仍只来自组长本地 .env，启动器绝不接触密钥内容。
    os.environ.update(
        {
            "DATABASE_URL": url,
            "UPLOAD_DIR": str(uploads),
            "ALLOWED_ORIGINS": json.dumps([args.origin]),
            "PYTHONUNBUFFERED": "1",
        }
    )
    if args.llm_mode == "fake":
        os.environ.update({"LLM_MODE": "fake", "LLM_PROVIDER": "fake"})
    if args.bad_model_a:
        os.environ["LLM_MODEL_A"] = BAD_MODEL_NAME

    worker_log = (root / f"worker-{args.uploads_name}.stdout.log").open("ab")
    worker = subprocess.Popen(
        [sys.executable, "-u", "-m", "app.platform.jobs", "--poll-seconds", "0.25"],
        cwd=BACKEND_DIR,
        env=dict(os.environ),
        stdout=worker_log,
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    atexit.register(lambda: worker.poll() is None and worker.terminate())

    settings = load_settings()
    if settings.llm_mode != args.llm_mode:
        parser.error(
            f"期望 LLM_MODE={args.llm_mode}，实际加载为 {settings.llm_mode}；请检查 backend/.env"
        )
    if args.bad_model_a and settings.llm_model_a != BAD_MODEL_NAME:
        parser.error("LLM_MODEL_A 覆盖未生效")
    app = create_database_app(settings)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
