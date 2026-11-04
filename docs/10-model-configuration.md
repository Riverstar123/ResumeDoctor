# 假模型与真实模型切换

展示站专用入口目前只启用 DeepSeek：忽略本地 `.env`，读取服务器环境变量，并清空
备用模型和 GLM 槽；通用目录及其他开发入口不变。部署配置见 [展示站部署](11-show-deployment.md)。

责任人：E 实现网关、目录与配置格式；A 把装配接入启动配置；组长在本地填写供应商凭证。开发默认使用 fake，只有显式设置 `LLM_MODE=real` 才可能发出真实请求。

本文对应 [Issue #23（AI-02）](https://github.com/Riverstar123/ResumeDoctor/issues/23)。真实调用验收属于 AI-03；本任务只用 HTTP stub 验证协议，不消耗真实额度。

2026-11-05 本地变更已加入岗位定向追问、独立报告事实审核和跨档案版本比较，当前提示为 `profile-v3`、`chat-v4`、`job-v2`、`report-v3`。下文说明当前实现；历史 AI-03 记录不替代本次真实供应商复验。本次更新尚未部署至学院服务器。

## 修改位置

| 位置 | 作用 |
|---|---|
| `backend/.env` | 本地私有配置，不进 Git；从 `backend/.env.example` 复制 |
| `backend/config/models.yaml` | 受控模型目录；保存公开 id、显示名、能力、环境变量映射，不保存密钥或端点 |
| `backend/app/llm/config.py` | 读取/校验目录，`build_llm(settings)` 按 `LLM_MODE` 装配 |
| `backend/app/llm/openai_compatible.py` | OpenAI-compatible Chat Completions 适配器 |
| Web 模型下拉菜单 | 从 `GET /api/v1/models` 选择可用 `model_id`；不能直接输入 key 或任意端点 |

`app.llm` 导入时不读 settings、不读目录、不连接网络。`build_llm()` 默认 fake；fake 模式不会读取 `models.yaml`。

## 服务端变量

| 变量 | fake | real |
|---|---|---|
| `LLM_MODE` | `fake` | `real` |
| `LLM_PROVIDER` | `fake` | `openai_compatible`（目前唯一支持的协议） |
| `LLM_BASE_URL` | 不使用 | 供应商 API base URL（含合法端口，不含查询/片段，包括空的 `?`/`#`），由适配器拼接 `/chat/completions` |
| `LLM_MODEL` | 不使用，可留空 | DeepSeek 默认实际模型名称；real 模式必须显式填写，旧演示值 `fake-default` 会被拒绝 |
| `LLM_API_KEY` | 留空 | DeepSeek 本地凭证 |
| `LLM_MODEL_A` | 可不设置 | DeepSeek 备用型号名称（与默认条目共用端点/凭证） |
| `LLM_MODEL_B` / `LLM_BASE_URL_B` / `LLM_API_KEY_B` | 可不设置 | 智谱 BigModel（GLM）条目的模型名与**独立端点/凭证**；不填则该条目省略 |
| `LLM_BASE_URL_A` / `LLM_API_KEY_A` | 可不设置 | 预留的独立备用槽（当前 `models.yaml` 未引用；改 env 名即可让备用型号完全独立） |

`models.yaml`（`version: models-v3`）的条目与供应商标签：

| 条目 | 供应商标签 | 模型 | 端点/凭证 |
|---|---|---|---|
| `real-default` | `deepseek` | `LLM_MODEL` | `LLM_BASE_URL` / `LLM_API_KEY` |
| `real-model-a` | `deepseek` | `LLM_MODEL_A` | 共用 `LLM_BASE_URL` / `LLM_API_KEY` |
| `real-model-b` | `bigmodel` | `LLM_MODEL_B` | `LLM_BASE_URL_B` / `LLM_API_KEY_B` |

`providers` 注册表把供应商标签映射到适配器协议（两家均为 `openai_compatible`）。未填写的条目不会出现在 `GET /models`，也不会被解析成其他模型；切换模型只能访问对应端点并携带对应凭证，错误时不跨供应商重试，不静默回退或换模型。默认条目缺变量时服务启动/装配阶段直接报 `MODEL_UNAVAILABLE`，错误只给出变量名。只填写 DeepSeek 三个变量即可完成单模型 smoke，第二家未配置不影响该路径。real 模式不会把旧演示占位 `fake-default` 当成实际模型名；未显式填写模型、或 base URL 含非数字/越界端口、用户名、查询或片段（含空的 `?`/`#`）时，同样在装配阶段失败。

目录条目字段：

| 字段 | 说明 |
|---|---|
| `id` | 稳定公开标识，任务冻结后不再变化 |
| `display_name` | 页面显示名，不含凭证 |
| `provider` | 公开供应商标签（`deepseek` / `bigmodel`），必须在目录的 `providers` 注册表声明，且其协议与 `LLM_PROVIDER` 一致 |
| `capabilities` | `profile_extract` / `profile_chat` / `job_extract` / `diagnosis_report` 的子集 |
| `enabled` | 停用条目不出现在列表、不能被解析 |
| `model_env` / `base_url_env` / `api_key_env` | 只写环境变量名，不写值 |

`version` 写入 `model_metadata.gateway_config_version`。修改实际模型、端点或能力时必须同时提升 `version`，让冻结快照能发现映射变化。

目录可声明 `reasoning_effort_by_model`，值限定为 low/high/max，并按实际模型名精确匹配；没有匹配时不发送该参数。v3 仅在 BigModel 槽的实际型号为 `glm-5.3` 时设置 low，避免默认深度推理耗尽原有输出预算；不影响其他 GLM 型号或 DeepSeek。依据为 [GLM-5.3 官方参数说明](https://docs.bigmodel.cn/cn/guide/models/text/glm-5.3)。输出达到上限的 finish_reason=length 会标记 OUTPUT_TRUNCATED，仍共用一次修复预算；3,000-token 报告上限与调用期限不变。

## 适配器行为

- 请求：`POST {LLM_BASE_URL}/chat/completions`，`Authorization: Bearer <key>`；`prompt_context["prompt"]` 作为 system 消息，其余数据与调用方传入的 JSON Schema 作为 user 消息；`temperature=0`，`response_format={"type":"json_object"}`；报告额外设置 `max_tokens=3000`。
- 响应：读取 `choices[0].message.content`，先解析 JSON，再用调用方提供的 JSON Schema 校验；符合 `06-ai-contract.md` 的“任意 Schema”约定。
- 超时：真实网关整次调用由 `timeout_seconds`（默认 45 秒）截止。非 fake 报告的生成与独立审核合计共用这份预算，HTTP、校验、退避和修复均计入；到期返回 MODEL_TIMEOUT，不再请求。
- 重试：429/5xx/网络错误与非法 JSON/不符 Schema 的输出**共用一次**重试预算；非法输出会追加一次格式修复消息。修复回显与指令同样计入输入上限，只使用剩余预算；剩余预算放不下修复指令时不再发送修复请求，直接以 `MODEL_OUTPUT_INVALID` 结束，不截断原始输入。401/403/404 等配置类错误不重试。
- 非 fake 报告通过 `generate_reviewed` 执行生成、确定性校验和独立事实审核。正常为两个 HTTP 请求；生成错误、审核格式错误与网络/限流等失败共用一次重试，最多三个 HTTP 请求。审核使用同一已选模型、独立提示 `report-grounding-v2`、过滤后的允许证据与冻结 JD 上下文，不是另选供应商；JD 不作为用户经历证据。实质性拒绝或不确定直接降级，不重试以换取通过，也不允许审核者改写候选。失败可返回脱敏 `reason_code`，完整契约见 [AI 契约](06-ai-contract.md)。
- 不支持独立审核的非 fake 网关拒绝报告，已有规则评分保留。明确标记的 fake 路径只检查确定性结构/来源规则，不运行独立语义审核，其通过结果不构成真实性保证。
- 错误码：`PROVIDER_UNAVAILABLE`、`MODEL_TIMEOUT`、`MODEL_OUTPUT_INVALID`、`INPUT_TOO_LONG`、`MODEL_UNAVAILABLE`；消息不包含密钥、端点或供应商响应正文。
- 输入上限：报告 20,000 字符，提取 30,000 字符；超限在发请求前失败。每次实际发送（包括格式修复重试）都按原始输入加本次新增文本核算。
- 调用记录：只保留 task_name、model_id、prompt_version、尝试次数、结果、耗时和输入字符数，不记录原文或密钥。

## 两家官方直连端点（公开信息）

| 供应商 | API base URL（填入对应变量，不含 `/chat/completions`） | 文档 |
|---|---|---|
| DeepSeek | `https://api.deepseek.com`（也兼容 `https://api.deepseek.com/v1`） | platform.deepseek.com |
| 智谱 BigModel | `https://open.bigmodel.cn/api/paas/v4` | open.bigmodel.cn/dev/howuse/introduction |

两者均提供 OpenAI-compatible Chat Completions；实际模型名、定价与限额以供应商官方页面为准（在 AI-03 验收时核对并记录，本文不预填）。密钥分别申请、分别填写，绝不交叉发送。

## 切换顺序

1. 复制 `backend/.env.example` 为 `backend/.env`，只在本地填写真实值；不要提交、发到 Issue/PR 或粘贴到聊天。
2. 确认 `backend/config/models.yaml` 的条目与 provider 正确，默认条目所需变量齐全。
3. 设置 `LLM_MODE=real`、`LLM_PROVIDER=openai_compatible`。
4. AI-03 已完成 INT-02 正式栈接线：`app/runtime.py` 的 `business_modules(settings)` 在 `LLM_MODE=real` 时用 `build_llm(settings)` 装配目录与网关，并向 M3 `GatewayIntake`、M5 `ReportService` 显式注入 QA-02 安全验收覆盖的联系方式过滤策略；`app.database`（API）与 `python -m app.platform.jobs`（worker）共用此组装，缺配置仍在启动阶段以 `MODEL_UNAVAILABLE` 失败。`app.integration` 是 INT-01 轻量合成栈，按设计保持固定 fake。
5. 重启 API 和 worker（两者必须使用同一份 `.env` 与同一 `models.yaml`），打开页面选择模型。
6. 在 AI-03 验收真实提取、报告、双模型切换和错误降级。相同确认快照换报告模型，评分必须保持不变。
7. 回滚：改回 `LLM_MODE=fake` 并重启 API 和 worker；页面必须重新显示演示标记。fake 不需要 key，也不会读取真实目录。

M3/M5 对非 fake 网关要求调用方显式提供已评审的隐私过滤策略（`privacy_filter`），否则 fail closed。real 组装当前显式注入 QA-02 安全验收覆盖的联系方式过滤（电话、邮箱、联系方式字段，见 `app/intake/privacy.py`、`app/reporting/privacy.py`）；学校/公司名仍可能发送，必须在页面 `VITE_PROCESSING_NOTICE` 告知中说明，不得把该策略描述成完整匿名化。

## 验收与复现

AI-02 的自动验收全部使用 `httpx.MockTransport`，不访问网络：

```sh
cd backend
python -m pytest tests/llm -q
python -m app.tools.check_contracts
ruff check app tests
ruff format --check app
```

测试覆盖：Chat Completions 请求形状与元信息、`real-model-a/b` 双模型映射、429 重试与共用预算、5xx 耗尽、超时不重试、非法 JSON/不符 Schema 的一次修复、401 不重试、输入超限、接近上限时修复重试的剩余预算与安全结束、空 `?`/`#` 等非法端点、未知/停用/能力不匹配的 `model_id`、缺配置启动失败、公开 DTO 与异常不泄露 key/base URL、fake 默认不读真实配置。

当前实现还包含 `tests/llm/test_reviewed_gateway.py`、`tests/reporting/test_grounding.py` 与定向追问测试，检查生成/审核共用期限和重试、拒绝不重试、逐项证据范围及提问不改档案。本轮验证见[优化记录](team/ux-benchmark-and-optimization.md)：真实供应商的报告生成与审核、只提问、回答整理三项合成烟测成功；真实语义误判率、供应商拒绝/超时及浏览器生产全链路仍需独立验收，不能用 stub 或 fake 结果替代。

## 限制

- 只承诺 OpenAI-compatible Chat Completions；Anthropic Messages 等协议需要新增独立适配器。
- 端点需要支持 `response_format={"type":"json_object"}`；不支持时由该端点返回 4xx，适配器明确报 `MODEL_UNAVAILABLE`，不会退回 fake 或换模型。
- AI-02 不调用真实供应商；真实 AI 与双模型 Web 验收见 [AI-03 记录](team/ai-03.md)（Issue #27）。
- 真实调用接线已由 AI-03 在 `app/runtime.py` 完成（INT-02 正式栈）；其他协议、完整匿名化或公网部署仍需新需求。
