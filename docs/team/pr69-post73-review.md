# PR #69 合入 #73 后的评审核对

基线：`362a875984bc879c788ba86d5a2defc892ec38b1`（已合入 #73）。原评审意见来自
[D 的 Request changes](https://github.com/Riverstar123/ResumeDoctor/pull/69#pullrequestreview-5779247086)。
本记录是作者复验，不替代 D 的独立复审，也不表示 PR 已通过或合并。

## 原问题的当前实现

- 助手问题上下文已在 `071848f` 修复：SQL worker/内存任务保留用户和助手各最近 10 条，
  由 `history_order` 传递顺序。助手消息只读，新增证据只允许用户原文。
- 多项要求共享证据已在 `071848f` 修复：审核输入集中存储完整证据，每项只引用授权 ID；
  审核输出也集中回显完整原文，仍校验逐项授权、逐字引用和覆盖范围。
- 原前端 URL 等待竞态与 QA-03 标签已修复；本轮重新验证当前整合版本。

## 本轮实际修复

发现历史窗口的排序仍以时间戳和随机 UUID 判定先后。同一时钟刻度中生成多条消息时，
SQL worker 可能读取成「下一问、回答、上一问」；公共消息列表也可能把不同轮次的用户
消息排在一起，影响简短回答的上下文。

新增 SQLite 和 PostgreSQL 回归均先在未修改实现上失败。测试固定时钟并让消息 UUID
顺序与对话顺序相反，覆盖提问、回答、后续问题、公开消息列表与租约恢复。

修复在既有档案行锁保护下读取最后一条消息时间；新消息时间相同或更早时递增 1 微秒，
确保新写入消息的顺序稳定。无需数据库迁移，不回填历史消息、不改变来源白名单。
测试只固定消息 ID，租约 token 仍正常生成，并断言恢复后 token 更新、旧租约失效。

## 补强共享证据验收

原 35 条要求共享长证据的回归扩展到 `matcher-v1/coverage-v1` 和 `matcher-v2/coverage-v2`。
除了检查输入/输出去重和字符上限，还执行正式 ReportService 与 OpenAI-compatible HTTP
适配器，使用 MockTransport 返回合成候选及审核回答。两种规则均实际发出两次请求并返回
报告，生成输出预算 6,000、审核使用独立预算；线上模型和真实密钥不参与。

## 本轮结果

| 检查 | 结果与范围 |
| --- | --- |
| 后端全量 | 1124 passed、0 skipped、1 warning；一次性 PostgreSQL、隔离集群、SQLite，合成模型 |
| 解析依赖与归档门禁 | 已提供官方旧 pypdf wheel、重新构建的 ZIP 和独立运行时，4+8 项均在全量内实际执行，不重复累计 |
| 前端单元 | 105 passed |
| QA-03 轻量 | 8 passed；本地真实 FastAPI/UI，合成端口/fake 模型 |
| 类型、生产构建、契约 | 通过；41 schemas、4 examples、18 业务路由，pending=[] |
| Ruff、格式、diff | 通过 |

后端警告为既有 Starlette/httpx 弃用提示。QA-03 的 INTERNAL_ERROR/PROVIDER_UNAVAILABLE
日志来自已声明的失败注入用例，相应用例通过。

命令与日志位于本地忽略目录 `output/pr69-current-review/`；部署包仅用于本机归档测试。
本轮没有 Windows 实机测试、真实付费模型调用或线上部署；未执行 QA-03 正式数据库浏览器
套件及既有主 mock 浏览器套件，不能将其他轮次的成绩计入本轮。

原评审中的 SQLite 清理锁与连接池建议继续由 #74 跟进，不属于本次顺序修复。

## 本地证据指纹

以下内容来自本轮实际命令，文件位于忽略目录，不提交模型响应或原始用户资料。

- `backend-final.log`：`bf7a0ba9a548917d0ec33ad89417132cf3640e57a0653a7185657b0d9965606d`
- `qa03.log`：`b3096862110f445e8ca2ade967f782f00d2b8f1440ef58d956d92d8678386bdc`
- `contracts.json`：`33742bbc38eacc5412394143ab5345ebc68c27d9dfbc7e705b7338f582149a5e`
- `resumedoctor-pr69-review.zip`：`aa1beb7549af5bd6cb72282615fbcdf9eddd8d728f8655e4c647808cf253e677`
