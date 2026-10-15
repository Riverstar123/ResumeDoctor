建议标题：`feat(m2): assemble P1 synthetic intake, scoring and fake gateway (INT-01)`

此正文用于 Draft PR；不同 JD 提取和 B 复现完成前不能标记 ready，发布状态以 GitHub 为准。

## 解决什么问题

关联 Issue：Closes #13

模块：M2 / 集成配置 / docs

原 API-01 装配全部为 M2 自有替身，无法证明团队模块可消费。新增 P1 组合根直接注入 C SyntheticIntake、D ScoringService、E FakeModelDirectory / FakeModelGateway，已有 B 页面通过 HTTP 模式实际访问 API。规范合成岗位的评分来自真实 coverage-v1 / matcher-v1，fake 报告消费既有 ScoreResult。

## 变更及影响

- `make dev` 指向 `app.integration:create_app`；API-01 全替身仍可通过 `make dev-api-fakes` 复现，不能混用评分预期。
- M2 边界映射 E 内部错误，确保不可用模型入队前 422、执行时失败保留具体码；校验模型元信息与冻结映射一致。
- 报告/导出为明确 P1 合成范围；网关失败后保留真实评分，score_only / partial 可读可导出。新增服务端可控的报告失败 factory，不从用户输入触发。
- 不改 HTTP Schema、DTO、依赖锁文件、迁移或 B/C/D/E 实现；无外部模型成本。
- **未完成：** C 的固定合成端口无法处理第二份不同 JD，已有严格 xfail 和实际浏览器失败证据。手工编辑第二岗位后的隔离验证已做，但不替代两份独立提取验收。C 的最小修正和 B 的复现要求见 `docs/team/int-01.md`；尚未取得队友接单或复现证据。

## 验证

本地锁定环境：Python 3.12.13 / uv 0.11.15；前端 Node 24.14.1 / npm 11.11.0，仅合成素材及 fake。

- `PYTHONUTF8=0 make test contracts lint`：272 passed、1 xfailed；36 Schema / 4 样例 / 18 路由，pending=[]；Ruff 通过。
- 新增装配集成测试：6 passed、1 xfailed，真实评分函数调用与手算基准、手工修正后的双岗位/模型隔离、失败降级及终态均覆盖。唯一 xfail 为独立不同 JD 提取，**不是验收通过**。
- frontend：`npm run types:check`、`npm run build`、`npm test` 通过，29 tests passed。
- 实际启动 `make dev` + `npm run dev:api`，Playwright CLI 操作对话、确认、岗位、模型选择和结果，浏览器请求与后端访问日志一致；成功/不同 JD 失败后的请求列表稳定。安全响应体在 `docs/team/evidence/int-01/`，完整步骤见交接文档。
- 干净 main 源码快照叠加本任务具名文件、不带私人配置/旧环境：新 venv 锁定安装后 `make test contracts lint` 仍为 272 passed / 1 xfailed，契约/Ruff 通过；前端类型/构建及 29 项单测通过。实际从该目录启动前后端，经 Vite 代理完成 TCP API 规范链、手工修正双岗位评分和导出。
- 实际报告失败工厂注入 E 网关 invalid_json：页面 score_only / partial、MODEL_OUTPUT_INVALID、保留 66.7、停止轮询，点击导出实际下载 Markdown 成功。安全响应体与干净目录 smoke 摘要已保存。

未执行/未完成：B 本人干净环境复现、C 修复后的独立双 JD 提取、队友 review、数据库 worker 与真实 AI；本轮不代表后续阶段验收。

## 检查

- [x] 范围与 Issue 一致；P1 限制明确
- [x] 运行、接口说明、合成样例入口同步
- [x] 只用合成数据，无真实个人资料、token、密钥；私人忽略规则未纳入业务差异
- [x] 已说明异常、固定输出缺口与消费者影响
- [ ] C 扩展合成端口后独立两岗位提取通过，移除严格 xfail 并重跑
- [ ] B（junnnh26）本人干净环境实际复现并留证
- [ ] 已邀请 E（y1324-cyber）、B（junnnh26）评审（当前未请求，不能勾选）
