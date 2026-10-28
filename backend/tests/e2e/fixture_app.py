"""QA-03 专用：带确定性故障注入的 fake 装配，只供端到端验收使用。

与生产装配（app.integration / app.database）相同的业务链路：真实 HTTP、
内存仓储、SyntheticIntake、确定性评分、经统一网关的假报告；区别仅在服务端
测试开关，开关只来自进程环境变量（RD_E2E_*），绝不从请求内容、请求头或
模型输出读取——与 FakeModelGateway「失败只来自服务端注入」的同一安全约束。

环境变量（均为服务端测试控制，文档见 docs/team/qa-03.md）：
- RD_E2E_FAILURES：JSON，task_name -> behavior（timeout/invalid_json/provider_unavailable）
- RD_E2E_REPORT_FAIL_INDEX / _BEHAVIOR：第 N 次 diagnosis_report 调用（0 基）
  按指定行为失败，用于「一个岗位成功、另一个降级」的可复现 partial；
  报告按诊断中岗位顺序逐个生成，因此注入是确定性的。
- RD_E2E_REPORT_FAIL_EVERY（可选，与 INDEX 互斥）：从 offset 起每 N 次调用
  失败一次（offset 用 INDEX 给），让多个用例共享同一进程时每个双岗位诊断
  都稳定复现「第二岗位降级」，不依赖请求内容。
- RD_E2E_REPORT_TIMEOUT：GatewayReporting 的单次报告调用超时（秒，默认 45）
- RD_E2E_TASK_FAILURES：JSON，task kind -> 错误码；让执行器在任务开始即失败
  （用于全失败诊断与运行中删除会话）
- RD_E2E_EXECUTOR_DELAY：执行器每个操作的固定延迟（秒，默认 0.01）；
  RD_E2E_DELAY_OPS：可选 JSON，只延迟这些操作前缀（如 ["diagnosis","scoring:"]），
  避免拖慢提取类前置任务

本模块不在生产代码目录，生产装配不 import 它；文件名没有 test_ 前缀，
不会被 pytest 收集。
"""

import asyncio
import json
import os

from app.intake import SyntheticIntake
from app.llm import FakeModelDirectory, FakeModelGateway
from app.main import create_app as create_platform_app
from app.platform.errors import PlatformError
from app.platform.fakes import FakeTaskExecutor
from app.platform.integration import GatewayCatalog, GatewayReporting
from app.scoring import ScoringService


class _E2eGateway(FakeModelGateway):
    """按调用序号注入一次报告失败；其余行为沿用 FakeModelGateway。"""

    def __init__(
        self,
        directory,
        *,
        fail_index=None,
        fail_every=None,
        fail_behavior="invalid_json",
        **kwargs,
    ):
        super().__init__(directory, **kwargs)
        self._fail_index = fail_index
        self._fail_every = fail_every
        self._fail_behavior = fail_behavior
        self._report_calls = 0

    def _should_fail_report(self, call_index: int) -> bool:
        if self._fail_every:
            return (
                call_index >= (self._fail_index or 0)
                and (call_index - (self._fail_index or 0)) % self._fail_every == 0
            )
        return self._fail_index is not None and call_index == self._fail_index

    async def generate_structured(
        self, task_name, prompt_context, output_schema, timeout_seconds, *, context
    ):
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
                task_name, prompt_context, output_schema, timeout_seconds, context=context
            )
        finally:
            if injected:
                # 只影响目标调用，不污染后续诊断。
                self.failures.pop("diagnosis_report", None)


class _E2eExecutor(FakeTaskExecutor):
    """按 task kind 立即失败，用于全失败场景；延迟由参数控制。"""

    def __init__(self, *args, task_failures=None, delay_ops=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._task_failures = dict(task_failures or {})
        # None 表示延迟所有操作；空序列表示不延迟任何操作。
        self._delay_ops = delay_ops

    async def before(self, operation: str) -> None:
        if self._delay_ops is None or any(operation.startswith(p) for p in self._delay_ops):
            await asyncio.sleep(self.delay_seconds)
        if operation in self._task_failures:
            raise PlatformError(422, self._task_failures[operation], "E2E 服务端注入的任务失败")


def _json_env(name):
    raw = os.environ.get(name)
    if not raw:
        return {}
    return json.loads(raw)


def create_app(settings=None):
    directory = FakeModelDirectory()
    gateway = _E2eGateway(
        directory,
        failures=_json_env("RD_E2E_FAILURES"),
        fail_index=(
            int(os.environ["RD_E2E_REPORT_FAIL_INDEX"])
            if os.environ.get("RD_E2E_REPORT_FAIL_INDEX")
            else None
        ),
        fail_every=(
            int(os.environ["RD_E2E_REPORT_FAIL_EVERY"])
            if os.environ.get("RD_E2E_REPORT_FAIL_EVERY")
            else None
        ),
        fail_behavior=os.environ.get("RD_E2E_REPORT_FAIL_BEHAVIOR", "invalid_json"),
    )
    timeout = float(os.environ.get("RD_E2E_REPORT_TIMEOUT", "45"))
    executor = _E2eExecutor(
        delay_seconds=float(os.environ.get("RD_E2E_EXECUTOR_DELAY", "0.01")),
        task_failures=_json_env("RD_E2E_TASK_FAILURES"),
        delay_ops=_json_env("RD_E2E_DELAY_OPS") if os.environ.get("RD_E2E_DELAY_OPS") else None,
    )
    app = create_platform_app(
        settings,
        executor=executor,
        catalog=GatewayCatalog(directory),
        intake=SyntheticIntake(),
        scoring=ScoringService(),
        reporting=GatewayReporting(gateway, timeout_seconds=timeout),
    )
    app.state.gateway = gateway
    app.title = "ResumeDoctor QA-03 E2E / deterministic failure injection, fake model"
    return app
