"""QA-03 正式装配（INT-02：PostgreSQL + 独立 worker + business_modules）的 e2e 支撑。

与 tests/e2e/fixture_app.py 的轻量合成装配相对：本模块的网关基于
app.platform.demo_gateway.IntegrationFakeGateway——M3 真实文件解析/对话、
M4 确定性评分、E 的 ReportService 报告校验与正式 Markdown renderer、
M2 数据库队列与租约全部走交付实现，只有模型调用被替换。

故障/同步开关同样只来自服务端进程环境，请求体、请求头和 JD/简历文本无法影响：
- RD_E2E_REPORT_FAIL_INDEX / _EVERY / _BEHAVIOR：按调用序号确定性地让某次
  diagnosis_report 以 invalid_json / provider_unavailable / timeout 行为失败
  （partial 变体）。
- RD_E2E_SYNC_DIR：worker 迭代轨迹（worker.log）目录；另在
  RD_E2E_BARRIER=1 时，diagnosis_report 在真正调用模型前写入 blocked
  标记并阻塞，直到同目录出现 release 标记；用于「运行中撤销会话」的
  确定性浏览器同步点（对应 test_int02.test_t16_revoke_during_real_report_call）。

本模块不在生产代码目录，生产装配不 import 它；文件名没有 test_ 前缀，
不会被 pytest 收集。
"""

import json
import os
import time
from pathlib import Path

from app.llm import FakeModelDirectory
from app.platform.demo_gateway import IntegrationFakeGateway

# 变体 -> 仅与本变体相关的进程环境（数据库与上传路径由 serve_real 统一设置）。
REAL_VARIANTS = {
    "success": {},
    "partial": {
        "RD_E2E_REPORT_FAIL_INDEX": "1",
        "RD_E2E_REPORT_FAIL_EVERY": "2",
        "RD_E2E_REPORT_FAIL_BEHAVIOR": "invalid_json",
    },
    "revoke": {
        # sync dir 由启动器按变体补入；只有显式打开 barrier 才阻塞报告调用。
        "RD_E2E_BARRIER": "1",
    },
}


def _write_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


class QaRealGateway(IntegrationFakeGateway):
    """登记合成素材的 fake 网关，叠加服务端确定性故障与删除同步点。"""

    def __init__(self, directory, *, fail_index=None, fail_every=None, fail_behavior=None):
        super().__init__(directory)
        self._fail_index = fail_index
        self._fail_every = fail_every
        self._fail_behavior = fail_behavior or "invalid_json"
        self._report_calls = 0
        self._sync_dir = (
            Path(os.environ["RD_E2E_SYNC_DIR"]) if os.environ.get("RD_E2E_SYNC_DIR") else None
        )
        self._barrier_enabled = os.environ.get("RD_E2E_BARRIER") == "1"
        self._barrier_passed = False
        self._block_timeout = float(os.environ.get("RD_E2E_BARRIER_TIMEOUT", "120"))

    def _should_fail_report(self, call_index: int) -> bool:
        if self._fail_every:
            offset = self._fail_index or 0
            return call_index >= offset and (call_index - offset) % self._fail_every == 0
        return self._fail_index is not None and call_index == self._fail_index

    async def _wait_release(self) -> None:
        sync_dir = self._sync_dir
        if sync_dir is None or not self._barrier_enabled or self._barrier_passed:
            return
        self._barrier_passed = True
        release = sync_dir / "release"
        _write_atomic(
            sync_dir / "blocked.json",
            {"at": time.time(), "pid": os.getpid(), "waiting_for": "release"},
        )
        deadline = time.monotonic() + self._block_timeout
        while not release.exists():
            if time.monotonic() > deadline:
                # 安全阀：只在控制面失联时放行，避免 worker 永久挂住。
                return
            await _interruptible_sleep(0.05)
        _write_atomic(sync_dir / "released.json", {"at": time.time()})

    async def generate_structured(
        self, task_name, prompt_context, output_schema, timeout_seconds, *, context
    ):
        # 与 tests.e2e.fixture_app._E2eGateway 同一注入层：失败开关必须覆盖整次
        # generate_structured 调用（含 FakeModelGateway 的 1 次格式修复重试），
        # 否则第一次 _produce 失败、第二次重试拿到 ok 行为就不会降级。
        injected = False
        rule_active = task_name == "diagnosis_report" and (
            self._fail_every or self._fail_index is not None
        )
        if rule_active and self._should_fail_report(self._report_calls):
            self.failures["diagnosis_report"] = self._fail_behavior
            injected = True
        if rule_active:
            self._report_calls += 1
        try:
            return await super().generate_structured(
                task_name,
                prompt_context,
                output_schema,
                timeout_seconds,
                context=context,
            )
        finally:
            if injected:
                # 只影响目标调用，不污染同进程后续诊断。
                self.failures.pop("diagnosis_report", None)

    async def _produce(self, task_name, prompt_context, behavior):
        if task_name == "diagnosis_report":
            # 同步屏障只阻塞第一次尝试；重试由 _barrier_passed 直接放行。
            await self._wait_release()
        return await super()._produce(task_name, prompt_context, behavior)


async def _interruptible_sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)


def gateway_from_env(directory=None) -> QaRealGateway:
    directory = directory if directory is not None else FakeModelDirectory()

    def int_env(name):
        return int(os.environ[name]) if os.environ.get(name) else None

    return QaRealGateway(
        directory,
        fail_index=int_env("RD_E2E_REPORT_FAIL_INDEX"),
        fail_every=int_env("RD_E2E_REPORT_FAIL_EVERY"),
        fail_behavior=os.environ.get("RD_E2E_REPORT_FAIL_BEHAVIOR"),
    )
