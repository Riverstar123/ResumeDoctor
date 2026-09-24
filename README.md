# ResumeDoctor · 简历诊断 Web 应用

面向求职者的小组项目：上传简历或通过对话整理经历，输入 1–5 个目标岗位 JD，获得逐岗位匹配评分、差距清单、修改建议和学习行动。

**当前阶段：文档设计，尚未开始业务代码开发。** 本仓库中的 API、数据库、目录和测试命令均为开发约定，不代表功能已经实现。已安装的第三方技能含原始脚本，仅作参考，不是本项目实现。

## 从这里开始

1. 全员阅读 [需求](docs/01-requirements.md)、[五人分工](docs/04-team-plan.md)。
2. GitHub 新手阅读 [协作上手](docs/team/github-guide.md)。
3. 在项目根目录启动 Claude Code，先读取 [CLAUDE.md](CLAUDE.md)，再阅读自己的模块说明。
4. 开发前评审 [API](docs/api/README.md)、[数据字典](docs/03-database.md)、[评分规则](docs/05-scoring.md)，完成 [待确认项](docs/00-decisions.md)。
5. 用 [任务清单](docs/team/backlog.md) 建 Issue，用 [验收计划](docs/07-testing.md) 检查结果。

## 文档导航

| 文档 | 解决的问题 |
|---|---|
| [决策与假设](docs/00-decisions.md) | 哪些已经确定，哪些只是默认提案 |
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

| 人员占位 | 模块 | 文档 |
|---|---|---|
| A（建议由有 GitHub 基础的你担任） | M2 后端平台、数据库和集成 | [M2](docs/modules/M2-platform.md) |
| B | M1 Web 前端全部页面 | [M1](docs/modules/M1-web.md) |
| C | M3 简历、对话与 JD 结构化 | [M3](docs/modules/M3-intake.md) |
| D | M4 证据匹配与确定性评分 | [M4](docs/modules/M4-scoring.md) |
| E | M5 AI 报告、模型网关与验收协调 | [M5](docs/modules/M5-report.md) |

人员和技术栈待团队确认。全员对自己模块的测试和文档负责；A 负责合并协调，不替全员完成开发。

## 当前仓库状态

- 有需求、契约、模块说明、协作模板和 Claude Code 项目指令。
- 没有 Web 页面、后端服务、数据库迁移或可运行应用。
- GitHub 地址与推送状态见 [仓库交接](docs/team/repository-status.md)。
