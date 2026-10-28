"""QA-03 正式栈的独立 worker 进程：真实数据库队列 + business_modules。

与生产入口 `python -m app.platform.jobs` 的区别仅在：
- 模型网关换成 tests.e2e.real_harness 的确定性故障/同步点网关（fake）；
- 每次认领与迭代结束向 RD_E2E_SYNC_DIR/worker.log 追加一行 JSONL，
  让浏览器用例能确定「撤销后原后台任务已经走完收尾」，而不是靠固定睡眠，
  从而可靠断言迟到结果没有被重新写回数据库。

不导入任何 app 之外的业务替身；上传解析、评分、报告校验、租约与失败写回
全部走交付实现。
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import time
from pathlib import Path

from app.llm import FakeModelDirectory
from app.platform.jobs.worker import Worker, create_worker

from .real_harness import gateway_from_env

logger = logging.getLogger("qa03-worker")


class TracingWorker(Worker):
    """在真实 run_once 外包一层迭代轨迹，不改变认领/执行/心跳语义。"""

    def __init__(self, *args, sync_dir: Path, **kwargs):
        super().__init__(*args, **kwargs)
        self._sync_dir = sync_dir
        self._seq = 0

    def _trace(self, event: str, task_id: str | None) -> None:
        self._sync_dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            {"seq": self._seq, "ts": time.time(), "event": event, "task_id": task_id},
            ensure_ascii=False,
        )
        with (self._sync_dir / "worker.log").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    async def run_once(self) -> bool:
        lease = await self.io(self.store.claim)
        if lease is None:
            return False
        self._seq += 1
        self._trace("claimed", lease.task_id)
        try:
            await self.execute(lease)
        finally:
            # execute 内部已吞掉 LeaseLost；无论成功、降级还是被撤销栅栏挡住，
            # 迭代结束都落轨迹，供用例等待并检查数据库侧无迟到写回。
            self._trace("iteration_done", lease.task_id)
        return True


async def serve(worker: TracingWorker, *, poll_seconds: float, stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()

    def request_stop(*_):
        loop.call_soon_threadsafe(stop.set)

    for signum in (signal.SIGINT, getattr(signal, "SIGBREAK", signal.SIGINT), signal.SIGTERM):
        try:
            signal.signal(signum, request_stop)
        except (ValueError, OSError):
            pass
    stopped = asyncio.create_task(stop.wait())
    try:
        while not stop.is_set():
            try:
                await worker.io(worker.store.repo.cleanup_expired)
                await worker.io(worker.store.repo.retry_file_cleanup, worker.upload_dir)
                claimed = await worker.run_once()
                await worker.io(worker.store.repo.retry_file_cleanup, worker.upload_dir)
            except Exception:
                # 与生产 worker 相同：瞬时故障下轮重试，不记录任何输入内容。
                logger.warning("worker_iteration_failed code=INTERNAL_ERROR")
                claimed = False
            if not claimed:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
                except TimeoutError:
                    pass
    finally:
        stopped.cancel()
        await asyncio.gather(stopped, return_exceptions=True)
        await worker.io(worker.store.repo.close)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--poll-seconds", type=float, default=0.25)
    args = parser.parse_args()
    if args.poll_seconds <= 0:
        parser.error("--poll-seconds must be positive")

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    sync_dir = Path(os.environ["RD_E2E_SYNC_DIR"])
    worker = create_worker(gateway=gateway_from_env(FakeModelDirectory()))
    tracing = TracingWorker(
        worker.store,
        intake=worker.intake,
        scoring=worker.scoring,
        reporting=worker.reporting,
        catalog=worker.catalog,
        upload_dir=worker.upload_dir,
        intake_factory=worker.intake_factory,
        sync_dir=sync_dir,
    )
    asyncio.run(serve(tracing, poll_seconds=args.poll_seconds, stop=asyncio.Event()))


if __name__ == "__main__":
    main()
