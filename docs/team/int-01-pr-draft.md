建议标题：`feat(m2): assemble P1 synthetic intake, scoring and fake gateway (INT-01)`

用于更新既有 PR #47；本地修复不代表 B 已复验或队友已批准，发布和合并状态以 GitHub 为准。

## 解决什么问题

关联 Issue：Closes #13
模块：M2 / 集成测试 / docs

P1 组合根连接 B 的 HTTP 页面、A API、C SyntheticIntake、D 真实 ScoringService 与 E FakeModelDirectory / FakeModelGateway。两份不同合成 JD 经独立提取、用户确认后分别诊断；评分来自真实 matcher-v1 / coverage-v1，报告明确为 fake。

## 变更及影响

- `make dev` 启动集成工厂，`make dev-api-fakes` 保留 API-01 全替身基准。
- 已同步最新 main（含 #48 实际 squash 提交 `8c0c9ac`），移除独立双 JD 的严格 xfail，保留原成功、quote 属于本 JD、Kubernetes 断言。
- 扩展正常验收到对话建档、各自确认、双岗位诊断、同名 r1 的状态/证据隔离、模型切换、历史结果不变与实际 P1 导出。原手工 Docker 编辑链作为额外版本回归保留，不代替独立双输入。
- 补未知合成输入 failed / 无结果且不新增、不覆盖已有岗位的回归。原真实评分函数 spy、网关失败 score_only/partial、单岗位与全岗位失败、模型停用检查保持。
- 不改 HTTP Schema、共享 DTO/端口、依赖锁文件、迁移或 B/C/D/E 业务实现；不调用外部模型。报告/导出为 P1 合成范围，未交付数据库 worker、真实 AI 或正式 #19 报告模块。
- 文档区分旧版 B 复现与修复版待复验；旧失败及手工编辑证据保留为历史，不覆盖成新成功证据。详见 [INT-01 记录](int-01.md)。

## 验证

本轮 macOS / Python 3.12.13 / uv 0.11.15 / Node 24.14.1 / npm 11.11.0，仅合成材料和 fake。

- 同步 main 后、修复前：原集成套件 6 passed / 1 failed，失败为 XPASS(strict)，复现 D 的修改意见。
- 修复后集成测试：**8 passed，无 xfail**。
- 全新 tracked 源码快照叠加具名补丁，不带私人配置或旧 venv；新环境按锁文件 `make setup` 后，`PYTHONUTF8=0 make test contracts lint`：**343 passed**，36 Schema / 4 样例 / 18 业务操作、pending=[]；Ruff check/format 通过（67 文件）。
- 干净目录 frontend：固定 Node/npm 下 `npm ci`、`npm run types:check`、`npm run build`、`npm test` 通过，**29 tests passed**。
- clean-source 实际启动 `make dev` / `npm run dev:api`，Playwright 经 Vite 真实 HTTP 完成对话、档案确认、两个不同 JD 独立提取/确认、B/A 模型诊断、岗位切换和实际 Markdown 下载。两岗位 66.7 / 0.0，同名 r1 的状态/证据独立，fake 标识可见。
- 实际失败工厂验证双岗位 score_only / MODEL_OUTPUT_INVALID、聚合 partial、评分保留和导出。成功/partial/failed 终态分别间隔 14.100 / 11.547 / 9.130 秒，任务 GET 总数稳定为 3→3 / 3→3 / 2→2，未用 ASGI 终态代替页面证据。安全响应与浏览器摘要见 `docs/team/evidence/int-01/`。
- 本机缓存 Chromium 以单进程无头模式运行；未声称 Windows 或跨浏览器验证。新增响应体经 Schema/跨响应/隐私检查，原始截图、网络列表和会话状态未提交。
- 子 agent 只读复核测试差异，未发现实质问题；该检查不代替 D/E/B 的独立团队验收。

## 未完成与交接

- B 已在旧 `ec07858` 干净环境复现并证实第二 JD 失败；修复版的完整双 JD 及失败轮询仍待 B 复验。
- D 的 CHANGES_REQUESTED 待其复审处理；指定 E/B 的最新批准未取得。本轮不自动请求评审、发布通知、合并或关闭 Issue。
- 本轮未运行真实 Windows、供应商、数据库/独立 worker、文件解析或完整 GatewayIntake 的 HTTP 来源事务，不把 P1 验证声称为后续阶段交付。
- 未知合成原文虽到 failed 且错误可见，但 C 的 IntakeError 当前由 M2 安全泛化为 INTERNAL_ERROR；本轮不声称错误码精细映射或任意 JD 能力已经交付。

## 检查

- [x] 范围与 Issue 一致，P1 限制明确
- [x] 两份不同 JD 正常测试覆盖，无 xfail 或跳过
- [x] 运行、接口与合成输入说明同步
- [x] 只用合成资料，原私人 .gitignore 不进入业务提交
- [ ] B 本人对修复版干净环境复验
- [ ] D 处理原修改请求，取得相应队友批准
