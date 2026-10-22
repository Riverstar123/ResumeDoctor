# M2 后台模块错误码映射修复

关联 [Issue #53](https://github.com/Riverstar123/ResumeDoctor/issues/53)，来源为 [RP-01 PR #52](https://github.com/Riverstar123/ResumeDoctor/pull/52) 的 M2 交接缺口；IN-03 也记录了同类问题。基线为已合入 JOB-01 的 main `d61f217`。

## 问题与行为

原内存任务的 `task_error()` 只保留 `PlatformError.info.code`。直接注入模块时，`GatewayError("MODEL_TIMEOUT", ...)`、`IntakeError("NO_TEXT_LAYER", ...)` 以及 RP-01 的 `ReportError` 均丢失具体错误码，显示为 `INTERNAL_ERROR`。持久 worker 另有 `.code` 映射，造成两条执行路径不一致。

现统一调用 [platform/errors.py](../../backend/app/platform/errors.py) 的 `task_error()`：

- 从平台异常、模块 `code` 或待保存 `ErrorInfo` 提取机器可读标识；只接受原后台白名单中的字符串。未知代码（包括内部 `PRIVACY_FILTER_REQUIRED`）和非法类型仍返回 `INTERNAL_ERROR`。
- `TimeoutError` 映射为 `TASK_TIMEOUT`；网关显式 `MODEL_TIMEOUT` 保持模型超时语义。
- 消息来自 M2 固定中文表，`details` 为空对象。异常原文、供应商 URL、文件路径和附加详情不进入结果；持久化前再次经过同一映射。
- 内存任务、持久 worker 和 `JobStore` 使用同一实现。后台失败仍通过 Task/DiagnosisItem 表达，轮询响应维持 HTTP 200；报告失败仍为 `score_only` 并保留规则评分和导出。

仅修改 M2 实现、测试和接口说明；没有修改 M3/M5 业务、共享 DTO、OpenAPI、迁移或依赖，也没有把 #52 的未合并代码纳入本 PR。入队前 HTTP 错误的既有映射不变；本次不代替 #19/#22 的完整装配和验收。

## 实测记录

日期：2026-10-22。macOS、Python 3.12.13、锁定依赖环境（含 database extra）；合成资料、fake/stub，无真实供应商请求或个人数据。

| 检查 | 实际结果 |
|---|---|
| 将新增任务错误回归放到原 main 隔离归档运行 | 19 failed / 8 passed，具体模块错误被压成 `INTERNAL_ERROR` 的反例可复现 |
| `python -m pytest tests/platform/test_task_errors.py -q` | 修复后 27 passed，覆盖白名单/未知与非法 code、详情脱敏、文件错误、任务查询、报告保分和导出 |
| 新临时 PostgreSQL 17.11 + `test_task_errors.py`、`test_jobs.py` | 59 passed，包含新增的 5 项数据库回归；核对失败任务无岗位版本写入、JSONB 中错误码/空详情、报告降级保分及导出 |
| 本修复分支完整后端 `PYTHONUTF8=0 python -m pytest -q` | 543 passed，0 skipped；包含真实 PostgreSQL 既有并发、恢复和隔离测试 |
| `python -m app.tools.check_contracts` | 36 Schema、4 样例、18 业务操作，pending=[] |
| `ruff check backend` / `ruff format --check backend` | 通过；90 个 Python 文件格式检查通过 |
| Alembic 迁移和 `alembic check` | 首次迁移通过；`check` 返回 `No new upgrade operations detected` |

另在临时组合目录，将本修复与 #52 的精确提交 `396288721023ea561398f16a1ac6c31c80944578` 组合验证：

- RP-01 既有测试与新增临时 ASGI 回归合计 **101 passed**。使用实际 `ReportService`，分别触发网关超时、非法输出、服务不可用和摘要校验 `ReportError`；确认具体错误码能查询和导出，评分保留。
- 再用实际 RP-01 服务和持久 worker 跑真实 PostgreSQL，超时与报告校验失败 **2 passed**，确认 `score_only`、具体错误码及 Markdown 导出。

联合目录及其临时测试不提交到本 PR，上述联合结果不混入本分支的 543 项测试。未验证真实供应商、浏览器或真实隐私过滤策略。

## 复现入口

按项目锁文件安装依赖，并设置迁移后的独立 `RD_TEST_DATABASE_URL`：

```sh
make test-db
make test contracts lint
```

针对新增任务/API 回归也可从 `backend/` 执行：

```sh
python -m pytest tests/platform/test_task_errors.py -q
```

只创建修复 PR，等待独立评审；不合并 PR、不关闭 #19/#22。
