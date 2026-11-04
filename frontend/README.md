# M1 Web 前端

当前真实业务模块、PostgreSQL 与独立 worker 的 HTTP 联调见 [INT-02 记录](../docs/team/int-02.md)。原交付边界与过去的模块测试见 DELIVERY.md / ACCEPTANCE.md；本 README 的命令用于当前代码。

页面覆盖 WEB-01、WEB-02、WEB-03，按仓库 OpenAPI 消费接口（当前包含可选 TaskResult.warnings、diagnosis_focus 与 questions_only 回显）。确定性评分、数据持久化与任务执行由对应后端模块负责。

前端支持明确标记的 mock 演示和真实 HTTP 两种模式。当前 HTTP 默认后端由 INT-02 装配真实解析/评分/报告、PostgreSQL 与独立 worker，模型仍为 fake，仅使用登记合成素材；不把该演示当作真实 AI 验收。

2026-11-05 本地已加入岗位定向补充、跨档案版本比较，并接入后端报告独立事实审核的失败降级。当前对话/报告提示为 `chat-v4` / `report-v3`；三项真实供应商合成烟测已通过，尚未部署至学院服务器。有限烟测不替代真实浏览器全链路或语言质量验收，详见[优化记录](../docs/team/ux-benchmark-and-optimization.md)。

## 启动

验证环境：Node **24.14.1**、npm **11.11.0**。版本记录于 `.nvmrc` / `package.json`，依赖使用精确版本和 `package-lock.json`。

```bash
cd frontend
npm ci
npm run dev
```

访问 `http://127.0.0.1:5173`。默认启动 **mock 演示模式**，无需后端或 API key。先勾选处理告知，再进入输入页。

- 对话：选择「对话整理」→「填入合成示例」→ 发送 → 检查并确认档案。
- 文件：选择 PDF/DOCX → 提交 → 核对模拟档案。mock 不解析真实文件，固定返回仓库的合成档案。
- 岗位：填入示例 JD → 提取 → 核对原文、类别、重要性、匹配方式 → 确认，可选择 1–5 个岗位。
- 诊断：点击开始 → 进度轮询 → 逐岗位报告 → 展开证据 → 导出 Markdown。
- 顶部「模拟场景」可选择部分成功、全部失败、提取失败、下次保存冲突或限流，验证后手动切回正常场景。

自定义输入在 mock 中只保留原文并提供待核对占位，不运行 M3 提取或 M4 真实评分。规范样例使用仓库固定的 66.7 分；自定义材料显示明确标注的 unknown 占位结果。mock 数据库仅在当前标签页的 `sessionStorage` 中模拟持久化，不是后端存储。

## 真实 API 联调

```bash
# 将 .env.example 复制为本地 .env，填写实际公开的处理告知
npm run dev:api
```

- `VITE_API_BASE_URL` 默认 `/api/v1`，开发代理 `/api` 到 `API_PROXY_TARGET`（默认 `http://127.0.0.1:8000`）。保留原始 Origin。后端默认允许 `http://localhost:5173`，HTTP 演示请打开该地址；如按终端打印打开 `http://127.0.0.1:5173`，须显式将其加入后端 `ALLOWED_ORIGINS`。
- `VITE_PROCESSING_NOTICE` 必须说明实际供应商、资料用途与外部传输情况；未配置时 HTTP 模式不允许新用户同意后上传。该字段是公开告知，不包含凭证。
- 可设置 `VITE_API_MODE=http` / `mock` 显式覆盖命令默认值。HTTP 模式错误不会退回 mock。
- `npm run build` 默认构建 HTTP 模式；离线演示用 `npm run build:mock`，然后 `npm run preview`。静态服务器需将页面路径回退至 `index.html`，并由服务端转发 `/api`。
- 所有业务请求使用 `credentials: include`；会话 cookie 由后端设置 HttpOnly。浏览器不读取 token，不直接请求模型供应商，不接收 API key。
- 模型目录与能力来自 `GET /models`。不支持当前能力的模型不可提交；切换不修改旧任务。
- 处理告知先于创建会话；恢复页面时通过 `GET /models` 校验原会话。401 清理本地资源索引并重新显示告知，不静默伪装原资料仍可用。

## 页面与状态

| 路由                      | 内容                                                                   |
| ------------------------- | ---------------------------------------------------------------------- |
| `/`                       | 处理告知、上传 / 对话输入；`?task=UUID` 恢复提取进度                   |
| `/profiles/:id`           | 结构化事实、原文证据、版本保存 / 确认、对话补充；支持任务参数          |
| `/profiles/:id/follow-up` | 从指定诊断要求生成问题、提交真实回答、核对确认新档案、沿用原 JD 再诊断 |
| `/jobs`                   | JD 提取 / 编辑 / 确认、公司背景、1–5 岗位选择与诊断创建                |
| `/diagnoses/:id`          | 诊断进度、逐岗位评分、证据、差距、改写、行动、模型与版本、导出与对比   |
| `/history`                | 当前标签页访问过的诊断链接                                             |

HTTP 模式 `sessionStorage` 仅记录会话公开元信息、资源 ID 和选择状态，不缓存档案、对话、JD 或报告原文。当前 API 无列表接口，因此历史页不是会话资源全集；持有报告 URL 时可按同一有效 cookie 重新获取。未提交的输入仅存在内存，刷新前请先保存。任务已被接受后，URL 可用于刷新恢复；离开页面会取消前端请求与计时，不取消后端任务。

版本编辑携带 `base_version`；保存生成新草稿，必须重新确认。409 时保留本地编辑，先读取服务端最新版本，再显式选择是否替换。报告按冻结版本读取档案/JD，不读取 latest 代替历史依据。用同一快照切换模型会创建新的诊断 ID。

定向补充入口位于报告非 met 要求旁，URL 携带 `diagnosis`、`item`、`requirement`，已接受的任务另带 `task` 以便刷新恢复。首轮“生成岗位定向问题”使用 `questions_only=true`：不修改档案、不保存 user 消息。用户实际回答才作为事实来源，内容变化后形成未确认草稿；核对确认后，使用新档案和原 JD 版本重新诊断。目标及任务归属由服务端验证，前端还核对任务回显，不能将其他岗位要求的结果应用到当前页面。

新报告的 `?before=原诊断ID&job=岗位ID` 预选岗位与比较对象。档案比较独立于原有同快照模型比较：必须同一档案 ID、不同已确认版本、相同 JD ID/版本和相同评分/匹配器版本。显示保存的分数、未知比例和逐要求状态/理由/证据变化，不在浏览器重算评分；证据按各自冻结档案读取，截止月份不同会提示。新增引用不等于新增能力，unknown→unmet 不标作“退步”。

非 fake 报告由后端分两次请求完成生成与独立事实审核，合计共享 45 秒与一次失败重试，正常两个、最多三个 HTTP 请求。审核拒绝或超时会保留规则评分；审核通过也不是事实正确性的保证。fake 只运行确定性检查，不运行独立语义审核；浏览器 mock 的固定结果不能用于证明补充事实后的真实分数变化。详见 [AI 契约](../docs/06-ai-contract.md)。

外观支持浅色、深色与跟随系统；仅将主题偏好 `rd:theme` 保存到 `localStorage`，存储不可用时仍可切换。主题在首屏加载前解析，表单、报告、弹窗与提示使用同一组语义颜色。

岗位页底部常驻操作区集中保存 JD、确认版本与开始诊断，并可跳到岗位列表或当前 JD。操作区复用原有校验与禁用条件，根据实际高度预留页面空间；无效字段会聚焦校验摘要。报告中“可审阅采用”的建议可选择并汇总复制，“待补充事实”的模板不能加入清单；选择只在当前报告内存中保留，切换岗位或建议内容时重置，不改变档案与评分。

本轮 GitHub 源码参考、评分标准对应关系与后续优化大纲见 [体验与 AI 价值优化记录](../docs/team/ux-benchmark-and-optimization.md)。

POST 上传 / 对话 / JD / 诊断 / 建档带 16–128 字符幂等键；同一失败提交在本页重试保留 key，修改输入或成功后新操作使用新 key。429 写请求禁用按钮至 `Retry-After` 到期，任务轮询也遵守等待时间。PUT 冲突不自动重发或覆盖。

## 工程结构

- `src/types/generated.ts`：由 `docs/api/openapi.json` 自动生成，不手写协议类型。
- `src/api/client.ts`：统一 HTTP 客户端、错误、multipart、幂等头、可取消串行轮询。
- `src/api/mock.ts`：独立演示传输层、合成快照与错误场景。不是生产评分或文件解析实现。
- `src/pages/`：输入、档案、岗位定向补充、岗位、报告与历史页。
- `src/components/`：结构化编辑器、模型选择、状态、错误、告知及删除确认。
- `src/lib/profileComparison.ts`：核验档案比较条件、对齐已保存要求和证据，计算展示差值；不实现 M4 评分。
- `src/validation.ts`：输入上限、证据引用、年月、JD 原文与要求合法性检查。真实来源、安全和权限由服务端再校验。
- `tests/`：Vitest 客户端 / 组件 / OpenAPI 契约 / 业务边界测试及 Playwright 浏览器测试。

## 验证

```bash
npx playwright install chromium
npm run check
npm run format:check
```

`check` 顺序执行类型契约漂移检查、TypeScript 与 HTTP 构建、Vitest、Playwright。浏览器测试自动启动两个开发服务：5173 的 mock 与 5174 的 HTTP 测试实例。后者使用浏览器路由 stub 验证真实 fetch 请求，不调用外部服务。

新增组件测试覆盖定向任务恢复、目标隔离、未保存编辑保护、确认后使用原 JD 重诊断，以及不同确认档案的比较门禁、快照证据和路由切换。比较中的变化值使用明确标记的合成保存结果；真实评分变化另需通过后端 M4 链路验证。本次完整回归的最终数量与执行结果在优化记录中补记，不沿用旧模块验收数量。

QA-03 有两套不经浏览器 stub 的真实 UI 端到端套件：

- `npm run test:e2e:qa03`（配置 `playwright.qa03.config.ts`，8 用例）：直连四个自启的 FastAPI **INT-01 合成装配**后端（8010–8013；success/partial/fail/slow 服务端确定性故障注入；SyntheticIntake 只要求 `%PDF-` 魔数，不做真实文件解析）与四个 http 模式 Vite 实例（5180–5183），不需要 PostgreSQL 或供应商凭证；覆盖 HTTP/UI 契约，不代表 INT-02 交付栈。
- `npm run test:e2e:qa03:db`（配置 `playwright.qa03-db.config.ts`，5 用例）：真实 UI → `app.database` 正式 FastAPI（8020–8022）→ **独立 worker 进程** → 启动器自管的一次性临时 PostgreSQL，http 模式 Vite 实例在 5190–5192；业务模块全部走交付实现（真 PDF/DOCX 解析、ReportService 校验、正式 Markdown renderer、数据库队列与租约），只有模型替换为登记合成素材的 fake 网关。需先准备 EDB 便携版 PostgreSQL 并设置 `RD_QA03_PG_HOME`（详见 [开发说明](../docs/08-development.md)），只用合成资料、不调用真实供应商；含五岗位黄金分、DOCX 分页提示、对话两轮 v3、partial 正式导出，以及撤销时旧 cookie 独立重放 401 与数据库十表零写回。

- `npm run test:e2e:ai03`（配置 `playwright.ai03.config.ts`）：AI-03 真实模型验收套件。启动器使用**生产入口**（`app.database` + `python -m app.platform.jobs` worker）；success 变体用库 `rd_ai03_success_test`，real 附加的 degrade 变体用独立库 `rd_ai03_degrade_test`，两套同时存活不互领任务。默认 `RD_AI03_MODE=fake` 仅用于开发调试（目录为 demo-model-a/b，不调用供应商）；只有显式 `RD_AI03_MODE=real` 才执行真实验收：API/worker 读取组长本地 `backend/.env`（`LLM_BASE_URL/LLM_MODEL/LLM_API_KEY/LLM_MODEL_A/LLM_MODEL_B`），目录为 real-default/real-model-a/real-model-b，并须设置公开告知 `RD_AI03_NOTICE`。成功变体验证真实提取/报告与同快照双模型平分；real 模式附加 degrade 变体，用被覆盖为不存在名称的 `LLM_MODEL_A` 取得供应商真实 4xx，验证 score_only 降级。需 `RD_AI03_PG_HOME` 或 `RD_QA03_PG_HOME`；证据写入 `test-results/ai03/`。

三套套件的覆盖范围与 T 编号映射见 [QA-03 记录](../docs/team/qa-03.md) 与 [AI-03 记录](../docs/team/ai-03.md)。

生成中的报告页会显示后台实际返回的评分/报告完成数、当前岗位、提交后等待时间与最近同步时间，已有评分和报告可以先查看。断线时“重新连接进度”只重新读取原任务；离开后可从当前标签页的诊断记录或保存的报告 URL 继续查看。记录列表对进行中任务自动更新。完整报告仍在任务终态统一导出，不展示未经校验的模型草稿或虚构剩余时间。

AI-03 对真实任务单独设置 315 秒终态等待和 15 分钟整条用例预算，覆盖实际提取与两轮五岗位报告；普通页面断言不放宽。该测试预算不会延长生产调用或任务期限。降级报告的 `model_metadata` 可以为空：没有报告就不应声称有“实际生成模型”，所选型号看诊断级 `model_id`。

| 验收      | 前端覆盖                                                                                            |
| --------- | --------------------------------------------------------------------------------------------------- |
| T01 / T03 | 文件提交与对话建档、编辑确认；真实 PDF/DOCX 及分页提示的 HTTP 实测见 INT-02                         |
| T04 / T06 | 409 不丢编辑、未确认阻止诊断、最多选五岗位、空 JD / 全忽略 / 重复要求校验                           |
| T05       | 五个岗位独立切换，固定版本、要求、证据和建议对应                                                    |
| T12       | partial / score_only / 全失败，保留已完成评分和导出                                                 |
| T19 / T20 | 能力筛选、A/B 模型切换、同快照评分不变、历史模型不变；真实双模型由 `test:e2e:ai03`（real 模式）验收 |
| T23       | Markdown 下载、URL 刷新恢复、历史冻结版本与模型元信息                                               |
| 其他      | 401/404/409/413/415/422/429、Retry-After、幂等键、取消轮询、移动布局、删除会话、HTML 按文本显示     |

测试结果与交接记录见 [交付记录](DELIVERY.md)，课堂操作建议见 [演示路线](DEMO.md)。

## 后续集成检查

1. A 启动 API / PostgreSQL / worker，核对会话 cookie、Origin、字段与状态。
2. C 使用实际文字 PDF/DOCX、扫描件、超限文件验证服务端解析与证据定位。测试中生成的 multipart 字节仅验证上传链路，不是解析正确性的证明。
3. D 核对所有分数与原文证据由服务端产生，前端只展示返回值。
4. 维护者于 2026-10-31 完成的双供应商真实网页验收属于历史版本，详见 [AI-03 记录](../docs/team/ai-03.md)。本次 `chat-v4` / `report-v3` 已通过有限的真实供应商合成烟测，仍须完整网页与双供应商验收；历史记录不能替代新版本验收。
5. 按 [总验收计划](../docs/07-testing.md) 完成 PostgreSQL、worker、会话隔离、资料清理及真实 AI 全链路检查。

DOCX 解析提示与档案关联，在本标签页会话中保留任务引用和明确关闭状态；刷新、侧栏返回和继续对话均可重新读取提示。不同档案互不混用，提示读取失败仍可编辑并重试；删除/过期会话清理本地引用。服务端内容仍按 cookie 归属校验，前端保存的任务编号不替代鉴权。
