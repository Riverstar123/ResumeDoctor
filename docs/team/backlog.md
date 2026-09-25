# 开发任务索引

全部任务已在 GitHub 创建。角色固定使用 A–E；每张 Issue 内有实施步骤、验收、评审人和 Claude Code 提示。本文是导航，不把“已创建”当作“已完成”。

## 开始顺序

1. 先完成自己的协作演练 #2–#6；五个 PR 全部合并后 A 开始 #7。
2. #7 公共骨架合并后：A 做 #8，B 做 #9，C 做 #10，D 做 #11，E 做 #12，五人并行。
3. 后续按下表依赖领取；依赖表示成果已经合并并验收，不只是 Issue 被关闭。
4. `status:blocked` 为创建时状态，负责人核对后手动移除并设为 `status:ready`；不需要再次申请开启开发。

## 协作演练

| 角色 | 任务 |
|---|---|
| A | [#2](https://github.com/Riverstar123/ResumeDoctor/issues/2) 完成首次 PR 并理解本模块 |
| B | [#3](https://github.com/Riverstar123/ResumeDoctor/issues/3) 完成首次 PR 并理解本模块 |
| C | [#4](https://github.com/Riverstar123/ResumeDoctor/issues/4) 完成首次 PR 并理解本模块 |
| D | [#5](https://github.com/Riverstar123/ResumeDoctor/issues/5) 完成首次 PR 并理解本模块 |
| E | [#6](https://github.com/Riverstar123/ResumeDoctor/issues/6) 完成首次 PR 并理解本模块 |

## P1 工程与假数据闭环 · 目标 2026-10-11

| 任务 | 负责人 | 前置成果 | 交付 |
|---|---|---|---|
| [#7](https://github.com/Riverstar123/ResumeDoctor/issues/7) SET-01 | A | [#2](https://github.com/Riverstar123/ResumeDoctor/issues/2), [#3](https://github.com/Riverstar123/ResumeDoctor/issues/3), [#4](https://github.com/Riverstar123/ResumeDoctor/issues/4), [#5](https://github.com/Riverstar123/ResumeDoctor/issues/5), [#6](https://github.com/Riverstar123/ResumeDoctor/issues/6) | 公共工程、共享 DTO 与验证入口 |
| [#8](https://github.com/Riverstar123/ResumeDoctor/issues/8) API-01 | A | [#7](https://github.com/Riverstar123/ResumeDoctor/issues/7) | 匿名会话与假任务 API 闭环 |
| [#9](https://github.com/Riverstar123/ResumeDoctor/issues/9) WEB-01 | B | [#7](https://github.com/Riverstar123/ResumeDoctor/issues/7) | 前端工程与 mock 页面全流程 |
| [#10](https://github.com/Riverstar123/ResumeDoctor/issues/10) IN-01 | C | [#7](https://github.com/Riverstar123/ResumeDoctor/issues/7) | 档案与 JD 数据校验和合成提取端口 |
| [#11](https://github.com/Riverstar123/ResumeDoctor/issues/11) SC-01 | D | [#7](https://github.com/Riverstar123/ResumeDoctor/issues/7) | 确定性加权评分与手算金标准 |
| [#12](https://github.com/Riverstar123/ResumeDoctor/issues/12) AI-01 | E | [#7](https://github.com/Riverstar123/ResumeDoctor/issues/7) | 模型目录与 FakeModelGateway |
| [#13](https://github.com/Riverstar123/ResumeDoctor/issues/13) INT-01 | A | [#8](https://github.com/Riverstar123/ResumeDoctor/issues/8), [#9](https://github.com/Riverstar123/ResumeDoctor/issues/9), [#10](https://github.com/Riverstar123/ResumeDoctor/issues/10), [#11](https://github.com/Riverstar123/ResumeDoctor/issues/11), [#12](https://github.com/Riverstar123/ResumeDoctor/issues/12) | 五模块假数据链路集成 |

## P2 核心功能与持久化 · 目标 2026-10-25

| 任务 | 负责人 | 前置成果 | 交付 |
|---|---|---|---|
| [#14](https://github.com/Riverstar123/ResumeDoctor/issues/14) DB-01 | A | [#8](https://github.com/Riverstar123/ResumeDoctor/issues/8) | 数据库迁移、资源版本与幂等事务 |
| [#15](https://github.com/Riverstar123/ResumeDoctor/issues/15) JOB-01 | A | [#14](https://github.com/Riverstar123/ResumeDoctor/issues/14), [#13](https://github.com/Riverstar123/ResumeDoctor/issues/13) | 数据库 worker、租约恢复与任务超时 |
| [#16](https://github.com/Riverstar123/ResumeDoctor/issues/16) IN-02 | C | [#10](https://github.com/Riverstar123/ResumeDoctor/issues/10), [#12](https://github.com/Riverstar123/ResumeDoctor/issues/12) | 对话建档与 JD 提取工作流 |
| [#17](https://github.com/Riverstar123/ResumeDoctor/issues/17) IN-03 | C | [#16](https://github.com/Riverstar123/ResumeDoctor/issues/16) | PDF/DOCX 文件输入与解析异常 |
| [#18](https://github.com/Riverstar123/ResumeDoctor/issues/18) SC-02 | D | [#11](https://github.com/Riverstar123/ResumeDoctor/issues/11), [#10](https://github.com/Riverstar123/ResumeDoctor/issues/10) | 要求匹配、同义词与证据状态 |
| [#19](https://github.com/Riverstar123/ResumeDoctor/issues/19) RP-01 | E | [#12](https://github.com/Riverstar123/ResumeDoctor/issues/12), [#11](https://github.com/Riverstar123/ResumeDoctor/issues/11) | 结构化诊断报告、校验和 Markdown 导出 |
| [#20](https://github.com/Riverstar123/ResumeDoctor/issues/20) WEB-02 | B | [#9](https://github.com/Riverstar123/ResumeDoctor/issues/9), [#10](https://github.com/Riverstar123/ResumeDoctor/issues/10) | 上传、对话与档案/JD 确认交互 |
| [#21](https://github.com/Riverstar123/ResumeDoctor/issues/21) WEB-03 | B | [#20](https://github.com/Riverstar123/ResumeDoctor/issues/20), [#19](https://github.com/Riverstar123/ResumeDoctor/issues/19), [#8](https://github.com/Riverstar123/ResumeDoctor/issues/8) | 多岗位报告、模型选择与导出页面 |
| [#22](https://github.com/Riverstar123/ResumeDoctor/issues/22) INT-02 | A | [#15](https://github.com/Riverstar123/ResumeDoctor/issues/15), [#17](https://github.com/Riverstar123/ResumeDoctor/issues/17), [#18](https://github.com/Riverstar123/ResumeDoctor/issues/18), [#19](https://github.com/Riverstar123/ResumeDoctor/issues/19), [#21](https://github.com/Riverstar123/ResumeDoctor/issues/21) | 真实业务模块与持久化全链路联调 |

## P3 质量与真实 AI 验收 · 目标 2026-11-05

| 任务 | 负责人 | 前置成果 | 交付 |
|---|---|---|---|
| [#23](https://github.com/Riverstar123/ResumeDoctor/issues/23) AI-02 | E | [#12](https://github.com/Riverstar123/ResumeDoctor/issues/12), [#19](https://github.com/Riverstar123/ResumeDoctor/issues/19) | 可配置真实模型适配器与一键切换说明 |
| [#24](https://github.com/Riverstar123/ResumeDoctor/issues/24) QA-01 | D | [#18](https://github.com/Riverstar123/ResumeDoctor/issues/18), [#16](https://github.com/Riverstar123/ResumeDoctor/issues/16), [#19](https://github.com/Riverstar123/ResumeDoctor/issues/19) | 评分回归集与报告证据一致性回归 |
| [#25](https://github.com/Riverstar123/ResumeDoctor/issues/25) QA-02 | C | [#17](https://github.com/Riverstar123/ResumeDoctor/issues/17), [#15](https://github.com/Riverstar123/ResumeDoctor/issues/15) | 输入安全、提示注入与资料清理验收 |
| [#26](https://github.com/Riverstar123/ResumeDoctor/issues/26) QA-03 | E | [#22](https://github.com/Riverstar123/ResumeDoctor/issues/22), [#24](https://github.com/Riverstar123/ResumeDoctor/issues/24), [#25](https://github.com/Riverstar123/ResumeDoctor/issues/25) | 假模型端到端验收与缺陷收敛 |
| [#27](https://github.com/Riverstar123/ResumeDoctor/issues/27) AI-03 | E | [#23](https://github.com/Riverstar123/ResumeDoctor/issues/23), [#26](https://github.com/Riverstar123/ResumeDoctor/issues/26) | 组长填写配置后的真实 AI 与双模型验收 |

## P4 演示与最终交付 · 目标 2026-11-09

| 任务 | 负责人 | 前置成果 | 交付 |
|---|---|---|---|
| [#28](https://github.com/Riverstar123/ResumeDoctor/issues/28) REL-01 | A | [#26](https://github.com/Riverstar123/ResumeDoctor/issues/26) | 可复现演示环境与运行交接 |
| [#29](https://github.com/Riverstar123/ResumeDoctor/issues/29) DEMO-01 | B | [#28](https://github.com/Riverstar123/ResumeDoctor/issues/28), [#27](https://github.com/Riverstar123/ResumeDoctor/issues/27) | 课堂演示路线与五人讲解彩排 |
| [#30](https://github.com/Riverstar123/ResumeDoctor/issues/30) FINAL-01 | E | [#29](https://github.com/Riverstar123/ResumeDoctor/issues/29), [#26](https://github.com/Riverstar123/ResumeDoctor/issues/26), [#27](https://github.com/Riverstar123/ResumeDoctor/issues/27) | 最终验收、遗留事项与提交检查 |

## 真实模型切换

E 在 #23 交付适配器和配置说明，组长本地填写配置后在 #27 完成真实调用验收。此前所有开发与自动测试均可使用 fake，最终课堂验收必须有真实 AI 调用证据。入口见 [模型配置](../10-model-configuration.md)。

截止时间：2026-11-10 前；最终交付检查目标：2026-11-09。各阶段日期是计划目标，实际进度以 Issue 验收与 PR 为准。
