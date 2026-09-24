# ResumeDoctor · 简历诊断 Web 应用

面向求职者的小组项目：上传简历或通过对话整理经历，输入 1–5 个目标岗位 JD，获得逐岗位匹配评分、差距清单、修改建议和学习行动。

**当前阶段：协作演练与开发准备。** 完成演练后按任务依赖进入开发。此仓库已提供开发契约和完整任务计划，应用代码由各模块任务交付。目标是在 2026 年 11 月 10 日前完成课程交付。

## 从这里开始

1. 全员阅读 [需求](docs/01-requirements.md)、[五人分工](docs/04-team-plan.md)。
2. GitHub 新手阅读 [协作上手](docs/team/github-guide.md)。
3. 在项目根目录启动 Claude Code，先读取 [CLAUDE.md](CLAUDE.md)，再阅读自己的模块说明。
4. 先完成 [启动导航](https://github.com/Riverstar123/ResumeDoctor/issues/1) 中自己的协作演练，再从 [任务索引](docs/team/backlog.md) 领取满足依赖的任务。
5. 实现遵循 [API](docs/api/README.md)、[数据字典](docs/03-database.md)、[评分规则](docs/05-scoring.md) 和 [项目基线](docs/00-decisions.md)，以 [验收计划](docs/07-testing.md) 检查结果。

## 文档导航

| 文档 | 解决的问题 |
|---|---|
| [项目基线](docs/00-decisions.md) | 技术栈、范围、开工规则与变更管理 |
| [需求与验收](docs/01-requirements.md) | 用户流程、MVP 范围、异常行为 |
| [架构与内部接口](docs/02-architecture.md) | 模块之间怎么配合 |
| [数据库](docs/03-database.md) | 表、字段、关系、事务、数据生命周期 |
| [分工与里程碑](docs/04-team-plan.md) | 五个人各交付什么，谁审谁 |
| [评分规则](docs/05-scoring.md) | 可复现的分数与证据解释 |
| [AI 契约](docs/06-ai-contract.md) | 提取、追问、诊断与失败降级 |
| [验收计划](docs/07-testing.md) | 如何证明整条流程可用 |
| [API 说明](docs/api/README.md) / [OpenAPI](docs/api/openapi.json) | 请求、响应、错误与数据结构 |
| [开发与部署约定](docs/08-development.md) | 后续环境准备及集成方式 |
| [技能参考取舍](docs/09-skill-reference.md) | 如何借鉴 hr-resume-screening |
| [GitHub 上手](docs/team/github-guide.md) / [Claude 提示模板](docs/team/claude-prompts.md) | 如何协作而不互相覆盖 |

## 五人模块

| 角色 | 模块 | 文档 |
|---|---|---|
| A | M2 后端平台、数据库和集成 | [M2](docs/modules/M2-platform.md) |
| B | M1 Web 前端全部页面 | [M1](docs/modules/M1-web.md) |
| C | M3 简历、对话与 JD 结构化 | [M3](docs/modules/M3-intake.md) |
| D | M4 证据匹配与确定性评分 | [M4](docs/modules/M4-scoring.md) |
| E | M5 AI 报告、模型网关与验收协调 | [M5](docs/modules/M5-report.md) |

角色始终使用 A–E。全员对自己模块的测试和文档负责；A 协调合并与集成。先用 fake 模型联调，E 交付真实模型配置入口后，由组长填写本地配置完成真实 AI 验收。

## 当前仓库状态

- [完整 Issues](https://github.com/Riverstar123/ResumeDoctor/issues) 与 [阶段里程碑](https://github.com/Riverstar123/ResumeDoctor/milestones) 是任务入口。
- 每个任务有负责人、前置依赖、范围、验收和 Claude Code 提示。
- 当前尚无应用实现；运行命令由工程任务交付，不把文档契约当作已运行功能。
- 仓库使用方式见 [协作指南](docs/team/github-guide.md)；模型切换入口见 [模型配置](docs/10-model-configuration.md)。
