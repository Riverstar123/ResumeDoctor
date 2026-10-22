"""Run with python -m app.platform.jobs; no API background queue is involved."""

import argparse
import asyncio
import logging
import signal

from .worker import create_worker

logger = logging.getLogger(__name__)


async def serve(worker, *, once=False, poll_seconds=1.0, stop=None):
    stop = stop if stop is not None else asyncio.Event()
    loop = asyncio.get_running_loop()
    installed = {}

    def request_stop(*_):
        loop.call_soon_threadsafe(stop.set)

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            installed[signum] = signal.getsignal(signum)
            signal.signal(signum, request_stop)
        except ValueError:
            # Embedders may run this in a thread; CLI runs in the main thread.
            installed.pop(signum, None)
    stopped = asyncio.create_task(stop.wait())
    active = None
    claimed = False
    try:
        while not stop.is_set():
            try:
                await worker.io(worker.store.repo.cleanup_expired)
                await worker.io(worker.store.repo.retry_file_cleanup, worker.upload_dir)
                active = asyncio.create_task(worker.run_once())
                done, _ = await asyncio.wait({active, stopped}, return_when=asyncio.FIRST_COMPLETED)
                if stopped in done:
                    break
                claimed = await active
                await worker.io(worker.store.repo.retry_file_cleanup, worker.upload_dir)
                if once:
                    return claimed
            except Exception:
                # Transient DB/storage faults are retried by the polling service.
                # No input, URL, driver exception or provider text is logged.
                logger.warning("worker_iteration_failed code=INTERNAL_ERROR")
                if once:
                    raise
                claimed = False
            if not claimed:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
                except TimeoutError:
                    pass
        return claimed
    finally:
        if active is not None:
            active.cancel()
            await asyncio.gather(active, return_exceptions=True)
        stopped.cancel()
        await asyncio.gather(stopped, return_exceptions=True)
        await worker.io(worker.store.repo.close)
        for signum, handler in installed.items():
            signal.signal(signum, handler)


def main():
    parser = argparse.ArgumentParser(
        description="ResumeDoctor PostgreSQL worker (business modules / fake model)"
    )
    parser.add_argument("--once", action="store_true", help="claim at most one task, then exit")
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    args = parser.parse_args()
    if args.poll_seconds <= 0:
        parser.error("--poll-seconds must be positive")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    worker = create_worker()
    asyncio.run(serve(worker, once=args.once, poll_seconds=args.poll_seconds))


if __name__ == "__main__":
    main()
