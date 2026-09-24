# M2 后端平台与集成

负责人：A。完成协作演练及当前 Issue 的前置成果后，按任务索引直接开工。

## 必读

[总需求](../01-requirements.md)、[架构/内部端口](../02-architecture.md)、[OpenAPI](../api/openapi.json)、[数据库](../03-database.md)、[评分](../05-scoring.md)、[AI 契约](../06-ai-contract.md)。

## 所有权

模块所有权目录：`backend/app/platform/、backend/app/api/、backend/app/contracts/、backend/migrations/`；对应模块测试由本人维护。共享契约需协调 A 和消费者。
会话与资源隔离、路由、持久化、版本/幂等、数据库任务 worker、文件生命周期和模块编排。

## 输入 / 输出

输入：OpenAPI、数据库文档、M3/M4/M5 内部 DTO。

交付：可独立验证的 API、迁移、假模块集成、worker 恢复和部署配置。

## 开发任务顺序

1. 先做会话、模型列表路由、共享 DTO 与假任务闭环。
2. 实现版本持久化、确认、幂等和访问隔离。
3. 实现数据库 worker 的租约、重试、超时和独立岗位提交。
4. 接入各真实模块，完成清理、导出路由和集成说明。

## 边界与协作

不把 AI/评分算法写进路由；不手工替别人模块兜底计算。

依赖关系：E 提供模型目录和网关；C/D/E 提供业务端口；B 消费 API。

## 验收与交接

优先完成 [验收计划](../07-testing.md) 的 T04/T06/T12/T13/T14/T15/T16/T21；提交一组正常和一组失败示例、实际测试命令、已知限制和集成步骤。能被假数据独立调用后再联调，不等所有人完成。

## 交给 Claude Code 的首个提示

> 先读 CLAUDE.md 和 docs/modules/M2-platform.md。从 docs/team/backlog.md 找到当前 Issue，检查演练及依赖成果已合并。前置未满足时只完成演练或准备；满足后实现该 Issue 的范围。保持 OpenAPI 字段与模块边界，使用 fake 模型独立验证，不生成整套应用。

## GitHub 任务入口

先完成 [#2](https://github.com/Riverstar123/ResumeDoctor/issues/2) 协作演练，再按依赖领取：

- [#7](https://github.com/Riverstar123/ResumeDoctor/issues/7) SET-01：公共工程、共享 DTO 与验证入口。
- [#8](https://github.com/Riverstar123/ResumeDoctor/issues/8) API-01：匿名会话与假任务 API 闭环。
- [#13](https://github.com/Riverstar123/ResumeDoctor/issues/13) INT-01：五模块假数据链路集成。
- [#14](https://github.com/Riverstar123/ResumeDoctor/issues/14) DB-01：数据库迁移、资源版本与幂等事务。
- [#15](https://github.com/Riverstar123/ResumeDoctor/issues/15) JOB-01：数据库 worker、租约恢复与任务超时。
- [#22](https://github.com/Riverstar123/ResumeDoctor/issues/22) INT-02：真实业务模块与持久化全链路联调。
- [#28](https://github.com/Riverstar123/ResumeDoctor/issues/28) REL-01：可复现演示环境与运行交接。
