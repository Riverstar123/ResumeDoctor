# 假模型与真实模型切换

责任人：E 实现网关、目录与配置格式；A 把装配接入启动配置；组长在本地填写供应商凭证。开发默认使用 fake，只有显式设置 `LLM_MODE=real` 才可能发出真实请求。

本文对应 [Issue #23（AI-02）](https://github.com/Riverstar123/ResumeDoctor/issues/23)。真实调用验收属于 AI-03；本任务只用 HTTP stub 验证协议，不消耗真实额度。

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
| `LLM_BASE_URL` | 不使用 | 供应商 API base URL（含合法端口），由适配器拼接 `/chat/completions` |
| `LLM_MODEL` | 不使用，可留空 | 默认实际模型名称；real 模式必须显式填写，旧演示值 `fake-default` 会被拒绝 |
| `LLM_API_KEY` | 留空 | 本地填写供应商凭证 |
| `LLM_MODEL_A` / `LLM_MODEL_B` | 可不设置 | 两个可选条目的实际模型名称 |

`models.yaml` 中 `real-default` 引用 `LLM_MODEL`，`real-model-a` / `real-model-b` 分别引用 `LLM_MODEL_A` / `LLM_MODEL_B`；三者共用 `LLM_BASE_URL` 与 `LLM_API_KEY`。未填写的条目不会出现在 `GET /models`，也不会被解析成其他模型。默认条目缺变量时服务启动/装配阶段直接报 `MODEL_UNAVAILABLE`，错误只给出变量名。real 模式不会把旧演示占位 `fake-default` 当成实际模型名；未显式填写模型、或 base URL 含非数字/越界端口时，同样在装配阶段失败。

目录条目字段：

| 字段 | 说明 |
|---|---|
| `id` | 稳定公开标识，任务冻结后不再变化 |
| `display_name` | 页面显示名，不含凭证 |
| `provider` | 必须与 `LLM_PROVIDER` 一致 |
| `capabilities` | `profile_extract` / `profile_chat` / `job_extract` / `diagnosis_report` 的子集 |
| `enabled` | 停用条目不出现在列表、不能被解析 |
| `model_env` / `base_url_env` / `api_key_env` | 只写环境变量名，不写值 |

`version` 写入 `model_metadata.gateway_config_version`。修改实际模型、端点或能力时必须同时提升 `version`，让冻结快照能发现映射变化。

## 适配器行为

- 请求：`POST {LLM_BASE_URL}/chat/completions`，`Authorization: Bearer <key>`；`prompt_context["prompt"]` 作为 system 消息，其余数据与调用方传入的 JSON Schema 作为 user 消息；`temperature=0`，`response_format={"type":"json_object"}`；报告额外设置 `max_tokens=3000`。
- 响应：读取 `choices[0].message.content`，先解析 JSON，再用调用方提供的 JSON Schema 校验；符合 `06-ai-contract.md` 的“任意 Schema”约定。
- 超时：单次调用由 `timeout_seconds`（默认 45 秒）截止，超时不重试。
- 重试：429/5xx/网络错误与非法 JSON/不符 Schema 的输出**共用一次**重试预算；非法输出会追加一次格式修复消息。401/403/404 等配置类错误不重试。
- 错误码：`PROVIDER_UNAVAILABLE`、`MODEL_TIMEOUT`、`MODEL_OUTPUT_INVALID`、`INPUT_TOO_LONG`、`MODEL_UNAVAILABLE`；消息不包含密钥、端点或供应商响应正文。
- 输入上限：报告 20,000 字符，提取 30,000 字符；超限在发请求前失败。
- 调用记录：只保留 task_name、model_id、prompt_version、尝试次数、结果、耗时和输入字符数，不记录原文或密钥。

## 切换顺序

1. 复制 `backend/.env.example` 为 `backend/.env`，只在本地填写真实值；不要提交、发到 Issue/PR 或粘贴到聊天。
2. 确认 `backend/config/models.yaml` 的条目与 provider 正确，默认条目所需变量齐全。
3. 设置 `LLM_MODE=real`、`LLM_PROVIDER=openai_compatible`。
4. 由 A 完成启动装配（把 `build_llm(settings)` 返回的目录与网关注入 API 和 worker）；当前 `app/database.py` 与 `app/integration.py` 仍固定 fake，未接线时设置 `LLM_MODE=real` 会在启动阶段明确失败，不会静默发请求。
5. 重启 API 和 worker（两者必须使用同一份 `.env` 与同一 `models.yaml`），打开页面选择模型。
6. 在 AI-03 验收真实提取、报告、双模型切换和错误降级。相同确认快照换报告模型，评分必须保持不变。
7. 回滚：改回 `LLM_MODE=fake` 并重启 API 和 worker；页面必须重新显示演示标记。fake 不需要 key，也不会读取真实目录。

M3/M5 对非 fake 网关要求调用方显式提供已评审的隐私过滤策略（`privacy_filter`），否则 fail closed；真实调用接线时一并配置，不要用 fake 过滤冒充真实数据政策验收。

## 验收与复现

AI-02 的自动验收全部使用 `httpx.MockTransport`，不访问网络：

```sh
cd backend
python -m pytest tests/llm -q
python -m app.tools.check_contracts
ruff check app tests
ruff format --check app
```

测试覆盖：Chat Completions 请求形状与元信息、`real-model-a/b` 双模型映射、429 重试与共用预算、5xx 耗尽、超时不重试、非法 JSON/不符 Schema 的一次修复、401 不重试、输入超限、未知/停用/能力不匹配的 `model_id`、缺配置启动失败、公开 DTO 与异常不泄露 key/base URL、fake 默认不读真实配置。

## 限制

- 只承诺 OpenAI-compatible Chat Completions；Anthropic Messages 等协议需要新增独立适配器。
- 端点需要支持 `response_format={"type":"json_object"}`；不支持时由该端点返回 4xx，适配器明确报 `MODEL_UNAVAILABLE`，不会退回 fake 或换模型。
- 本任务不调用真实供应商；真实 AI 与双模型 Web 验收见 AI-03。
- 真实调用接线、隐私过滤策略和页面展示由 A/AI-03 在联调阶段完成。
