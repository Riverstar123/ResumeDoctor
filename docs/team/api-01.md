# API-01：匿名会话与假任务 HTTP 联调

对应 [Issue #8](https://github.com/Riverstar123/ResumeDoctor/issues/8)，主责 A，维护者本轮指定评审 D（`mysteriesy`，账号来源：[CLAUDE.md](../../CLAUDE.md#角色与-github-账号)）。本记录交付可运行的 fake API；真实提取、确定性匹配、报告、数据库和独立 worker 尚待各自任务集成。

## 授权、基线与范围

维护者在本轮明确要求“不用管 #6，启动 #8；后续行动先暂时不要管前置依赖”。据此实施，不把缺失的演练或消费确认记为已经通过。此前逐项依赖核查保留真实结论：#7 的 [PR #38](https://github.com/Riverstar123/ResumeDoctor/pull/38) 已合并且 D 已复审批准；#6 未交付，其他演练评审/同步及 C/E 消费确认缺口仍待团队补齐，本轮不再作为开工门槛。

分支 `codex/api-01` 从更新后的 main `1949e71774b73806dee000769bdaec81d3891cc5` 创建，复用 #7 的 DTO、async Intake/Reporting 端口、同步 Scoring/导出及 `TaskContext(model_id=...)`。没有修改 C/D/E 业务目录或 B 前端。原 `.gitignore` 私有指南规则保留，不纳入本业务交付。

| 实现 | 文件与替身标识 | 后续替换 |
|---|---|---|
| HTTP 路由、依赖与统一 Error | [api/routes.py](../../backend/app/api/routes.py)、[api/errors.py](../../backend/app/api/errors.py) | B 消费同一 OpenAPI；无新增业务字段 |
| 会话与资源版本/归属 | [InMemoryRepository](../../backend/app/platform/repositories/memory.py)，`is_fake=True` | [#14 DB-01](db-01.md)：PostgreSQL、版本与幂等事务、持久化清理；原导入路径由包重导出保持兼容 |
| 入队、轮询与任务编排 | [service.py](../../backend/app/platform/service.py)、[FakeTaskExecutor](../../backend/app/platform/fakes.py)，`is_fake=True` | #15：独立数据库 worker、租约、领取重试、崩溃恢复 |
| 模型目录 | [FakeModelCatalog](../../backend/app/platform/catalog.py)，`is_fake=True` | E 的 #12 目录通过 `ModelCatalog.list_models/resolve` 注入 |
| 提取/评分/报告/导出 | [FakeIntake/FakeScoring/FakeReporting](../../backend/app/platform/fakes.py)，均 `is_fake=True` | #13 按 #7 ports 装配 C/D/E 的模块；真实模型另按 E 的后续任务接入 |

默认提取不推断事实：对话保存原文和演示回复，档案保留旧事实；JD 创建一条 `manual_review` 占位要求，用户可手工编辑。默认评分将每条非 ignored 要求标记 unknown，score=0、unknown_weight_ratio=1；该固定替身行为来自 fakes.py，不是材料质量判断，也不是 [M4 手算样例](../05-scoring.md#手算基准)的 66.7。目录的 display_name、provider=fake、报告和导出均明确标记演示来源。

## 运行与 cookie/Origin

按 [README](../../README.md#本地后端开发) 的实际命令安装并启动：`make setup`、`make dev`。默认 `http://127.0.0.1:8000`，单进程，`LLM_MODE=fake`；不要求数据库或 paid key。新增上传依赖 [python-multipart 0.0.32](https://pypi.org/project/python-multipart/0.0.32/) 已精确固定在 [pyproject.toml](../../backend/pyproject.toml) 和 [uv.lock](../../backend/uv.lock)，未更新其他包版本。

浏览器推荐通过 B 的同源代理访问 `/api/v1`，代理目标 `http://127.0.0.1:8000`，所有请求 `credentials: "include"`。保留浏览器真实 Origin，不伪造或删除它。默认 `ALLOWED_ORIGINS=["http://localhost:5173"]`；若前端地址改为 `http://127.0.0.1:5173`，明确加入该固定 Origin，不能改成 `*`。直接跨端口调用也需要 credentials；`localhost` 与 `127.0.0.1` 不应混用来规避 SameSite 限制。

所有业务读取需要 HttpOnly `rd_session`；所有写请求以及预检检查可信 Origin，CLI 也需发送已配置的 Origin。cookie 为 SameSite=Lax，固定七天不过访问续期，只保存随机 token 的哈希。重复创建有效会话仍返回原 session；过期 cookie 返回 401 并清除，用户明确重新创建后获得新会话。DELETE 成功立即撤销 token、删除本会话内存资源并取消任务，不保留可写回的后台任务。

本地 HTTP 用 `SESSION_COOKIE_SECURE=false`；HTTPS 部署必须设置 true。模板见 [backend/.env.example](../../backend/.env.example)。当前不支持 real 模式、多进程共享或重启恢复，重启后 cookie 对应的内存会话无效。

## B 的调用路线

下面脚本使用新建合成资料与服务端返回的 UUID。它可以在 B 的同源开发页面控制台运行；实际页面应把错误映射到 UI、离开页面停止轮询。轮询读取 HTTP 200 不代表成功，必须看 task.status；202 仅表示受理。用户重试同一次网络请求沿用同一个 key，主动发起新任务生成新 key。

```javascript
async function runFakeApi() {
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  async function request(method, path, body, key) {
    const response = await fetch(`/api/v1${path}`, {
      method, credentials: "include",
      headers: {
        ...(body === undefined ? {} : {"Content-Type": "application/json"}),
        ...(key ? {"Idempotency-Key": key} : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (response.status === 204) return null;
    const data = await response.json();
    if (!response.ok) throw new Error(`${response.status} ${data.error.code}: ${data.error.message}`);
    return data;
  }
  async function terminal(taskId) {
    for (;;) {
      const response = await fetch(`/api/v1/tasks/${taskId}`, {credentials: "include"});
      if (response.status === 429) {
        await sleep(1000 * Number(response.headers.get("Retry-After") || 2));
        continue;
      }
      const task = await response.json();
      if (!response.ok) throw new Error(task.error.code);
      if (["succeeded", "partial", "failed"].includes(task.status)) return task;
      await sleep(2000);
    }
  }
  function resultOf(task) {
    if (task.status === "failed") throw new Error(task.error.code);
    return task.result;
  }

  await request("POST", "/session", {consent_version: "v1"}); // 200 Session
  const directory = await request("GET", "/models");
  const modelId = directory.default_model_id; // 目录当前为显式 fake 模型。
  let profile = await request("POST", "/profiles", {content: {
    overview: "合成课程演示", as_of_month: "2026-09", facts: [], evidence: [],
  }}, crypto.randomUUID()); // 201 Profile
  const chat = await request("POST", `/profiles/${profile.id}/messages`, {
    base_version: profile.version, content: "我在合成课程项目中描述了一段经历。", model_id: modelId,
  }, crypto.randomUUID()); // 202 TaskAccepted
  const profileResult = resultOf(await terminal(chat.task_id));
  profile = await request("GET", `/profiles/${profileResult.resource_id}?version=${profileResult.version}`);
  const messages = await request("GET", `/profiles/${profile.id}/messages`);
  profile = await request("POST", `/profiles/${profile.id}/confirm`, {version: profile.version});
  const jobAccepted = await request("POST", "/jobs", {
    raw_text: "合成 JD：需要 Python 应用证据。", company_context: "", model_id: modelId,
  }, crypto.randomUUID());
  const jobResult = resultOf(await terminal(jobAccepted.task_id));
  let job = await request("GET", `/jobs/${jobResult.resource_id}?version=${jobResult.version}`);
  job = await request("POST", `/jobs/${job.id}/confirm`, {version: job.version});
  const accepted = await request("POST", "/diagnoses", {
    profile: {id: profile.id, version: profile.version},
    jobs: [{id: job.id, version: job.version}], model_id: modelId,
  }, crypto.randomUUID());
  const diagnosisResult = resultOf(await terminal(accepted.task_id));
  const diagnosis = await request("GET", `/diagnoses/${diagnosisResult.resource_id}`);
  const exportResponse = await fetch(`/api/v1/diagnoses/${diagnosis.id}/export`, {credentials: "include"});
  if (!exportResponse.ok) throw new Error((await exportResponse.json()).error.code);
  return {profile, job, messages, diagnosis, markdown: await exportResponse.text()};
}
runFakeApi().then(console.log).catch(console.error);
```

上传路线使用 FormData(file, model_id)，不手工设置 multipart Content-Type（浏览器需要生成 boundary），并带 Idempotency-Key。路由检查整体请求边界、10 MiB 文件大小、PDF 签名/DOCX 容器成员；当前提取仍是明确的上传替身，不检查文字层/20 页、不执行真实 PDF/DOCX 解析。成功结果是空事实草稿，用户仍需检查并确认。真实文件内容安全、解析和清理由 #17 与后续集成任务验收，不把 fake 成功算作 T01/T02 全通过。

## 异常和可控失败

| 行为 | HTTP / task / 处理 |
|---|---|
| cookie 无效或撤销 | 401 SESSION_EXPIRED；停止轮询，用户明确创建新会话 |
| 外部 Origin 或缺失 Origin 的写请求 | 403 ORIGIN_FORBIDDEN；修正固定 Origin 和代理配置 |
| 其他会话资源，包括修改/确认/消息/任务/导出/诊断引用 | 404 RESOURCE_NOT_FOUND；与不存在资源使用相同错误 |
| 非法 JSON、字段、UUID、版本、幂等头 | 422 VALIDATION_ERROR；Error schema；不返回原输入或私有字段名 |
| 旧 base_version、旧版本确认 | 409 VERSION_CONFLICT；GET 最新版本核对 |
| 同档案任务尚在运行 | 409 PROFILE_BUSY；等终态后新提交 |
| 同 key 不同操作/内容 | 409 IDEMPOTENCY_CONFLICT；相同请求重试沿用 key，新操作换 key |
| 无效/停用/能力不匹配模型 | 入队前 422 MODEL_UNAVAILABLE；若入队后停用，task failed/MODEL_UNAVAILABLE；不回退 |
| 未确认版本或无可评分 JD | 422 UNCONFIRMED_VERSION / NO_SCORABLE_REQUIREMENTS；整个诊断不创建半成品 |
| 写速率/并发限制 | 429 RATE_LIMITED；按 Retry-After 等待；分别来自需求中的 20 次/分钟、2 个并发任务 |
| 处理中/全失败的诊断导出 | 409 NOT_READY；partial 可导出已完成评分和失败标记 |
| 模块/模型失败 | 轮询 HTTP 200，task failed/error；报告失败但评分保留为 score_only，聚合 partial |

统一 HTTP 错误为 `{"error":{"code":"VERSION_CONFLICT","message":"资料已更新，请刷新后重试","details":{}},"request_id":"服务端生成的UUID"}`（示意，不是实测请求 ID）。服务异常只记录 request_id/task_id 与固定错误码；不记录 token、输入、供应商异常文本或内部路径。

在停止普通开发服务后，可用相同入口装配一次可重现的失败服务器（仅本地 fake，无 key）：

```sh
uv run --project backend --frozen python - <<'PY'
import uvicorn
from app.main import create_app
from app.settings import Settings
from app.platform.fakes import FakeTaskExecutor
app = create_app(Settings(llm_mode="fake"), executor=FakeTaskExecutor(
    failures={"job_parse": "MODEL_TIMEOUT"}
))
uvicorn.run(app, host="127.0.0.1", port=8000)
PY
```

POST /jobs 仍返回 202 task_id，轮询到 failed、result=null、error.code=MODEL_TIMEOUT。这些故障开关只来自服务端注入，用户经历/JD 文本不会触发开关。测试还用 asyncio.Event 暂停任务，覆盖运行中撤销、编辑冲突、执行前停用模型、总超时；它们是可控模拟，不是供应商或 worker 的真实故障验收。

## 验收条目、证据与结果

2026-10-13 评审修复后，本机 macOS，实际 Python 3.12.13 / uv 0.11.15（来源：版本命令及工程锁定配置）。本轮默认 fake；没有 paid key、真实个人资料或模型调用。实际网络服务与 JavaScript 文档检查沿用 2026-10-12 的记录，其余下表检查已在同步 main 12285de 后重跑。

从根 Makefile 执行 `PYTHONUTF8=0 make test contracts lint`。为隔离本机配置及失效代理，本机临时使用 `UV_NO_CONFIG=true UV_OFFLINE=true UV_NO_SYNC=true UV_CACHE_DIR=/private/tmp/resumedoctor-api-01-uv`，复用已有安装环境，不宣称重新建立干净克隆。新增 multipart 已用官方 PyPI 执行锁定和安装；锁文件只增加该包。

| 验收条目 | 文件 / 实际证据 | 结果 |
|---|---|---|
| 成功闭环、DTO、轮询终态、读取与导出 | [test_api.py](../../backend/tests/platform/test_api.py)：test_successful_http_chain_and_export；test_task_running_to_success_with_explicit_gate | 通过；成功链覆盖零延时与默认延时，只要求终态及可读结果；独立测试用 started/gate 明确停在 running，释放后验证 succeeded 与结果读取，不依赖轮询捕获短暂状态 |
| 超长 min_months 输入与版本原子性 | [test_boundaries.py](../../backend/tests/platform/test_boundaries.py)：test_overlong_min_months_is_422_without_creating_a_version | 修复前实测 4301 位数字 PUT 返回 500；修复后 422 VALIDATION_ERROR，版本仍为 1，版本 2 不存在，无输入泄漏；普通目标 12 仍可生成版本 2 |
| T15 独立会话隔离 | test_t15_every_owned_route_404_and_no_cookie_401 的 14 组路由 | 通过；先创建真实所属资源，再用独立 jar 验证读取/历史/修改/确认/消息/任务/诊断/导出/诊断引用 404；无 cookie 401；无合成私有标记泄漏 |
| 失败、脱敏及终态错误 | test_failures_are_terminal_and_sanitized；[test_boundaries.py](../../backend/tests/platform/test_boundaries.py) 的内部异常与无效端口输出测试 | 通过；可控 MODEL_TIMEOUT、未知异常 INTERNAL_ERROR；轮询成功而 task 失败；未泄漏异常中的合成 key/path/原文标记 |
| T16 撤销中断与固定过期 | test_running_revoke_prevents_late_writes；test_cookie_reuse_expiry_secure_origin_and_revocation | 通过；运行时撤销、旧 cookie 401、清空资源、阻止写回；Secure 实际 HTTPS cookie jar、固定过期及哈希存储 |
| T04/T13 版本/幂等 | test_idempotency_busy_limit_and_version_conflict；test_invalid_conversation_output_is_atomic | 通过；同 key 同资源/首次状态、异内容 409；busy；编辑后后台 VERSION_CONFLICT；无半成品消息/版本 |
| T06 限制与事务 | test_reject_unconfirmed_duplicate_and_unscorable_atomically；test_six_jobs_and_empty_jd_are_rejected | 通过；未确认、重复 JD 版本、空/无可评分 JD、第六项；无新任务/半诊断 |
| T12 报告降级和岗位失败 | test_partial_score_only_export_and_frozen_history 的报告/评分两分支 | 通过；另一岗位保留成功，partial 的 score_only/failed 可读、可导出，历史版本固定 |
| T21 与冻结选择 | 模型能力、停用、SpyIntake/SpyReport 及快照测试 | 通过；无效/能力不足不入队，执行前停用失败；默认值/目录映射变化不修改旧任务上下文和元信息 |
| 统一错误、Origin、限流与总超时 | 验证错误、预检、限流/24h 幂等保留、总超时测试 | 通过；Error schema、固定 CORS、Retry-After 可读；缩短测试控制总截止时间后 TASK_TIMEOUT，不需等待真实五分钟 |
| 完整 pytest | make test | 182 passed in 3.50s；同步 main 12285de 后复测，包含已合并 SC-01/SC-02/QA-01、原 #7 回归和平台 HTTP 测试 |
| Schema 与生成路由比较 | make contracts；[check_contracts.py](../../backend/app/tools/check_contracts.py) | 36 个命名 Schema、4 份样例、18 个业务操作通过；pending=[]；保持 GET /healthz |
| 静态检查 | make lint | Ruff check / format --check 通过，41 个 Python 文件 |
| 实际网络服务 | make dev；urllib 实际 localhost HTTP，独立 CookieJar | 28 次 HTTP 检查通过；JD running→succeeded，诊断 running→succeeded，结果和导出可读；另 jar 404、无 cookie/撤销后 401；实际 /openapi.json 比较无 pending；临时服务验证后停止 |
| 交接文档与契约范围 | 本地目标检查、Node `--check`、与 origin/main JSON 比较 | 62 个本地目标存在，B 的 JavaScript 示例语法通过；OpenAPI 仅阶段描述变化、HTTP schema 未变。浏览器脚本尚待 B 实际执行 |

OpenAPI 的结构、状态码、安全定义未变；只修正 info.description 中“没有运行服务”的过时阶段说明。FastAPI 新版 UploadFile 默认 Schema 使用 contentMediaType，设计要求 format=binary；WireUploadFile 仅调整上传参数生成的 Schema 展示，保留原上传解析/校验，不改设计或放宽比较器。路径 UUID、查询版本、响应头和全部 Error 响应也实际参与比较。

评审修复仅捕获 `min_months` 的整数转换 `ValueError`，使用现有 422 `VALIDATION_ERROR`；没有增加共享 DTO 的长度限制或改变评分规则。D 在 Windows 上报告的测试时序问题改为事件同步验证；此处 macOS 回归通过，修复后的 Windows 复测仍需 D 完成。

尚未验收：本次修复的真实 Windows 复测、本机浏览器与 B 实际页面联调；真实 PDF/DOCX 解析/页数/文字层；数据库事务、多进程、worker 崩溃恢复 T14、物理文件清理；真实 AI 与双模型 T22；真实 M4 与 HTTP 诊断接入。C/E 端口消费确认仍需队友给出。本地 HTTP 和测试替身通过不等于上述项目通过。

## 本轮收尾

本地实现与验证完成，维护者已授权暂不按依赖阻塞本轮，并明确授权提交 #8 PR、请求 D 实际评审。交付范围保持 #8；没有启动下一张 Issue。PR 使用 [仓库模板](../../.github/pull_request_template.md)，关联 Closes #8，说明替身与 #14/#15 的替换边界。

提交前核验指南忽略规则、未跟踪状态与逐文件暂存清单，原有本地 .gitignore 修改不纳入业务 PR。评审修复已同步包含 SC-01/SC-02/QA-01 的 main 并重新验证；API 默认仍使用明确标识的 FakeScoring，真实评分接入留给 #13。提交、推送与再次请求 D 评审不代表评审通过；合并及 Issue 关闭待后续验收，不在本次授权内。
