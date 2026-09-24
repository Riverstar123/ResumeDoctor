# 假模型与真实模型切换

责任人：E 实现网关与配置；A 接入启动配置；组长在本地填写供应商凭证。开发默认使用 fake，真实请求仅在明确启用 real 后发生。
本文规定配置交付格式；入口文件由 AI-02 创建。应用实现前不要执行不存在的启动命令。

## 修改位置

| 位置 | 作用 |
|---|---|
| `backend/.env` | 本地私有配置，不进 Git；从 `backend/.env.example` 复制 |
| `backend/config/models.yaml` | 受控模型目录；保存公开 id、显示名、能力及环境变量映射，不保存密钥 |
| `backend/app/llm/` | fake 与真实 provider 适配器；新增不同协议时在此扩展 |
| Web 模型下拉菜单 | 从 GET /api/v1/models 选择可用 model_id，不能直接输入 key/任意端点 |

## 服务端变量

| 变量 | fake | real |
|---|---|---|
| LLM_MODE | fake | real |
| LLM_PROVIDER | fake | openai_compatible（首个适配器标识） |
| LLM_BASE_URL | 不使用 | 所选兼容端点的 API base URL，由适配器统一拼接请求路径 |
| LLM_MODEL | fake-default | 默认实际模型名称 |
| LLM_API_KEY | 留空 | 本地填写供应商凭证 |
| LLM_MODEL_A / LLM_MODEL_B | 可不设置 | 两个可选条目的实际模型名称 |

目录中的 default 条目引用 LLM_MODEL，另外两个条目引用 LLM_MODEL_A/B。开发先使用同一供应商的两个不同型号；扩展到不同供应商时，各条目显式引用独立 base_url_env、api_key_env、model_env，不能静默共享不兼容配置。
公开 model_id 与实际模型名称分离。目录声明 id、display_name、provider、capabilities、enabled 和环境变量名；API 只公开用户选择所需元信息。缺少所需环境变量的条目不能作为可用模型返回；默认条目必须有效。
首个真实适配器使用 OpenAI-compatible Chat Completions 协议。不同协议的供应商需要新增适配器，不能仅改 URL 就声称支持所有模型。

## 切换顺序

1. 完成 AI-02，确认 fake 和真实适配器的 HTTP stub 测试通过。
2. 在本地 `backend/.env` 填写实际 API 地址、模型与密钥；不发到 Issue、PR 或聊天。
3. 在受控模型目录启用对应条目，设置 LLM_MODE=real。
4. 按 README 的实际命令重启 API 和 worker，打开页面选择模型。
5. 在 AI-03 验收真实提取、报告、双模型切换和错误降级。相同确认快照换报告模型，评分必须保持不变。
6. 回到演示模式时改 LLM_MODE=fake 并重启；页面必须明确显示演示标记。

代码和配置模板由 E 提供；组长只需填写实际值，不需要改前端或评分算法。凭证未配置不妨碍之前的开发、联调和自动测试，但真实 AI 验收必须在最终交付前完成。
