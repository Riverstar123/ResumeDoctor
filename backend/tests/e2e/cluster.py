"""本地临时 PostgreSQL 集群的单飞管理（仅 QA-03 正式栈 e2e 使用）。

不注册系统服务、不监听非环回地址、不创建业务库；集群数据放在调用方指定的
ASCII 临时根目录（initdb 在含非 ASCII 字符的路径上会失败）。多个变体的
启动器并发执行时，用文件锁保证 initdb/pg_ctl start 只发生一次，之后各自
创建并迁移独立的名称含 test 的数据库（队列互不抢任务）。

生产代码与 CI 都不依赖本模块；需要真实 PostgreSQL 的正式验收入口仍是
`make test-db`（RD_TEST_DATABASE_URL 指向自行迁移的专用测试库）。
"""

import contextlib
import json
import socket
import subprocess
import time
from pathlib import Path

import psycopg


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@contextlib.contextmanager
def _cluster_lock(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    handle = open(root / "cluster.lock", "a+b")
    try:
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
    except ImportError:
        import fcntl

        fcntl.flock(handle, fcntl.LOCK_EX)
    try:
        yield
    finally:
        handle.close()


def _connectable(host: str, port: int, dbname: str = "postgres"):
    try:
        with psycopg.connect(
            f"host={host} port={port} dbname={dbname} user=postgres connect_timeout=2",
            autocommit=True,
        ) as conn:
            conn.execute("SELECT 1")
        return True
    except psycopg.Error:
        return False


def _wait_ready(host: str, port: int, *, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _connectable(host, port):
            return
        time.sleep(0.25)
    raise RuntimeError(f"PostgreSQL cluster did not become ready on port {port}")


def ensure_cluster(pg_home: Path, root: Path) -> tuple[str, int]:
    """返回 (host, port)；必要时 initdb 并启动集群，幂等。"""
    pg_home = Path(pg_home)
    root = Path(root)
    data = root / "pgdata"
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    port_file = root / "port.json"

    if port_file.exists():
        port = json.loads(port_file.read_text(encoding="utf-8"))["port"]
        if _connectable("127.0.0.1", port):
            return "127.0.0.1", port

    def adopt_running() -> int | None:
        """上次启动器在写 port.json 前被杀死时，从 postmaster.pid 恢复端口。"""
        pid_file = data / "postmaster.pid"
        if data.exists() and pid_file.exists():
            lines = pid_file.read_text(encoding="ascii", errors="replace").splitlines()
            if len(lines) >= 4 and lines[3].strip().isdigit():
                candidate = int(lines[3])
                if _connectable("127.0.0.1", candidate):
                    port_file.write_text(json.dumps({"port": candidate}), encoding="utf-8")
                    return candidate
        return None

    with _cluster_lock(root):
        if port_file.exists():
            port = json.loads(port_file.read_text(encoding="utf-8"))["port"]
        else:
            port = adopt_running() or _free_port()
        if _connectable("127.0.0.1", port):
            return "127.0.0.1", port

        def run_quiet(command: list[str]) -> None:
            # EDB 的 Windows 工具在中文系统上按 GBK 输出；initdb 短命，可按字节捕获。
            result = subprocess.run(command, capture_output=True)
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).decode("gbk", errors="replace")
                raise RuntimeError(f"{' '.join(command[:2])} failed: {detail}")

        def run_pgctl(arguments: list[str]) -> None:
            # pg_ctl start 派生出的 postmaster 会继承管道句柄并长期存活，
            # capture 输出会让 communicate() 永久阻塞；输出交给 -l 日志与 DEVNULL。
            result = subprocess.run(
                [str(pg_home / "bin" / "pg_ctl"), *arguments],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if result.returncode != 0:
                tail = (logs / "pg.log").read_text(encoding="utf-8", errors="replace")[-2000:]
                raise RuntimeError(f"pg_ctl {' '.join(arguments[:1])} failed:\n{tail}")

        if not data.exists():
            run_quiet(
                [
                    str(pg_home / "bin" / "initdb"),
                    "-D",
                    str(data),
                    "-U",
                    "postgres",
                    "-A",
                    "trust",
                    "-E",
                    "UTF8",
                    "--locale=C",
                ]
            )
        (root / "socket").mkdir(parents=True, exist_ok=True)
        options = (
            f"-p {port} -c listen_addresses=127.0.0.1 "
            f"-k {root / 'socket'} -c fsync=off -c full_page_writes=off"
        )
        run_pgctl(
            ["-D", str(data), "-l", str(logs / "pg.log"), "-o", options, "-w", "-t", "60", "start"]
        )
        _wait_ready("127.0.0.1", port)
        port_file.write_text(json.dumps({"port": port}), encoding="utf-8")
        return "127.0.0.1", port


def ensure_database(host: str, port: int, name: str) -> str:
    """创建（若缺）并迁移指定的一次性数据库，返回 sqlalchemy URL。"""
    with psycopg.connect(
        f"host={host} port={port} dbname=postgres user=postgres", autocommit=True
    ) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
        if not exists:
            # 名称由启动器固定生成（仅小写字母/下划线/test），不接受外部输入。
            conn.execute(f"CREATE DATABASE {name}")
    url = f"postgresql+psycopg://postgres@{host}:{port}/{name}"
    _migrate(url)
    return url


def _migrate(url: str) -> None:
    import os

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    backend = Path(__file__).resolve().parents[2]
    with create_engine(url).connect() as conn:
        migrated = conn.execute(
            text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
        ).scalar()
        if migrated and conn.execute(text("SELECT version_num FROM alembic_version")).scalar():
            return
    config = Config()
    config.set_main_option("script_location", str(backend / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    os.environ["RD_DATABASE_URL"] = url
    command.upgrade(config, "head")


def stop_cluster(pg_home: Path, root: Path) -> None:
    data = Path(root) / "pgdata"
    if not data.exists():
        return
    subprocess.run(
        [str(Path(pg_home) / "bin" / "pg_ctl"), "-D", str(data), "-m", "fast", "stop"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
