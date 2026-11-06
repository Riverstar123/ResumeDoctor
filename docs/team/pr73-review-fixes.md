# PR #73 修改意见修复

本轮基于同步提交 `365c260`，针对 huih02427-cmyk 在 PR #73 提出的三条修改意见。不改变 #69 合入的功能，不修改评分权重、LLM 提示或模型预算。

## 三条意见与最终行为

1. [同事实匹配保留当前到岗安排冲突](https://github.com/Riverstar123/ResumeDoctor/pull/73#discussion_r4476912731)：`same_fact` 仍只允许同一事实满足 AND 条件，但天数、月数、到岗时间和全职安排的冲突在完整冻结档案中检查。肯定/否定记录及不同当前值的冲突保留双方证据，结果为 unknown/conflicting_evidence；不会因某条记录满足门槛而忽略另一条。不同学历的正常差异仍允许独立匹配，分散到不同记录的到岗字段也不能被 same_fact 拼接。
2. [立即到岗与月份比较](https://github.com/Riverstar123/ResumeDoctor/pull/73#discussion_r4476912743)：与具体年月进行 eq/gte/lte 比较时，将 immediate 在比较中解释为 `profile.as_of_month`；不读取运行时日期，不写回属性。与同一冻结月份的记录视为月份等价。JD 若要求明确立即到岗，仅提供当前或过去月份不能证明当前承诺，返回 unknown；明确未来月份为 unmet，显式 immediate 为 met。
3. [学历完成状态与在读属性一致性](https://github.com/Riverstar123/ResumeDoctor/pull/73#discussion_r4476912751)：同一学历 completed=true 与 enrolled、completed=false 与 completed、以及同时出现互斥 enrollment 值均在前端、M3 和 M2 拒绝保存。前端错误链接定位到“是否完成”，不会自动更改属性或证据。历史矛盾资料仍可由 matcher-v2 解释为 unknown/conflicting_evidence，也不能凭该事实证明已完成学历；其他无矛盾学历独立满足时仍可 met。只有一方未知不补猜；历史 matcher-v1 不变。

## 复现与回归

先添加期望行为用例，在未修改产品逻辑的 `365c260` 上运行：新增边界使后端出现 23 项失败，前端真实 ProfileEditor 编辑组件出现 3 项失败，覆盖三条意见。随后修复并补齐肯定/否定、等价到岗月份及独立学历等边界。

- `backend/tests/scoring/test_conditions.py`：profile/same_fact 两种范围、四类到岗字段、合法输入经过 M3/M2 与保存前评分重算、冻结月份 eq/gte/lte、历史学历冲突及独立学历、禁止跨记录拼接；不改写输入。
- `backend/tests/platform/test_education_status.py`：M3/M2 互斥状态拒绝、未知/一致状态兼容；真实 ASGI HTTP 创建和编辑均返回 422，未保存新版本，也未修改原内容。
- `frontend/tests/structured-fields.test.tsx`：实际 ProfileEditor 双向切换完成状态后提示关联字段错误，保留原属性与证据；改回一致状态后可通过校验。

本轮增加 47 项后端参数化用例、6 项前端用例。上述回归使用合成资料，没有提交原简历或 JD。

## 最终验证

| 检查 | 结果 | 范围 |
|---|---|---|
| 定向评分与学历保存回归 | 83 passed | 两个后端文件 |
| 后端全量 | 1109 passed、12 skipped、1 warning；40.43 秒 | 专用 PostgreSQL、隔离集群与 SQLite，fake 模型 |
| 前端单元测试 | 105 passed，13 个文件 | 含真实编辑组件回归 |
| QA-03 | 8 passed；42.0 秒 | 真实 FastAPI + 真实 UI，合成端口/fake 模型 |
| 既有浏览器流程 | 16 passed；1.3 分钟 | 合成数据/模拟服务 |
| 前端类型与生产构建 | 通过 | TypeScript、生成类型与 Vite |
| 契约/路由 | 通过 | 41 个 schema、4 个示例 |
| Ruff、格式、diff 检查 | 通过 | 本轮代码与测试 |

跳过项与同步验收相同：4 项未配置官方旧版 pypdf 3.17.4 wheel；8 项未配置全新安装包和全新运行时环境。未重做 Windows、全新安装包或线上验收。

## 原虚构案例的冻结材料回归

复用上一轮已保存的三个真实供应商快照，不再次发送材料或调用模型。三个快照均通过新增档案校验、未改写内容，重新匹配计分也均与保存结果一致：35.7/100，自动计分范围 73.68%，未知权重 63.16%。最终快照的已保存报告再次通过业务校验和独立审核响应的引用/覆盖检查。数字及结果来自本地 `frozen-case.log` 和 `original-case-validation.json`。

上一轮的真实模型调用、调试失败及人工复核记录仍见 [同步验收](pr73-sync-verification.md)。本轮为确定性规则、保存及 UI 修复验证，不冒充新的真实模型端到端复验。尚未部署展示站或合并 PR。

## 本地证据指纹

以下文件位于被忽略的 `output/pr73-review-fixes/`，只保留本地核对用途，文件本身不入库。

- `before.log`：`f7d7a0d651acaf213c3e74f6b90130862873151094f057c5d0828712f5bec8e7`
- `frontend-before.log`：`6c514705339b051bad2cd47f58e6368270cc78ca1fd8feeb47bc0531134d26fd`
- `targeted-final.log`：`726978791b4d15424f7c3c0e0f31501b402096f6019bfa478839d1d6c4b443fb`
- `backend-final.log`：`9dad9248ac40eba154aac935e21eca22b1f44242c81ae1d1bc432e9d4b1db371`
- `frontend.log`：`d7f2bcf07d64bedcc63a03cbb21ffba58c590b49ec0ae430f9d73fa7648bc49d`
- `qa03.log`：`9796bf458adcd6b50a0c8810000258b025a8bb5271dfb2ea21b617c874155868`
- `browser.log`：`41a7ae4832416e2a718831ba6cf8a78ca8bc173dbd6306ce13067cfd057b8b52`
- `frozen-case.log`：`89e8ecdf280e8377c8e896c572d5869af1368ea2b326d95e4e9bdfb7be026dca`
- `original-case-validation.json`：`a07a46b61307a755913991b3a3c04e4260045747cdb159979abf2d3c0dc29067`
