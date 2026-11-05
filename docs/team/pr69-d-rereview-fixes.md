# PR #69 D 复审三项问题修复

2026-11-06（北京时间），基于 `f295f685286e920194e11cb0e5b2ae098978ef20`。
评审来源：[D 最新 Request changes](https://github.com/Riverstar123/ResumeDoctor/pull/69#pullrequestreview-5788750165)。
本记录为作者修复和验证，不替代原评审人的复审，不表示 PR 已批准或上线。

## 问题与修复

1. **same_fact 隐藏同名技能/证书冲突。** 现在对每个技能/证书条件先用完整冻结档案核对
   相关冲突，再在单个事实内判断 AND 条件。肯否冲突及证书进度冲突保留双方引用并返回
   unknown/conflicting_evidence。正常不同名称、不同学历/经历不按此规则混同；独立的 OR
   备选仍可满足，单个 AND 仍不能跨记录拼接。旧 v1 规则及评分权重不变。
2. **Worker 将两类历史合计再次截断。** 删除 Worker 中的合计 10 条切片，传递 JobStore
   已按用户/助手各 10 条限制的完整序列。GatewayIntake 的角色窗口、顺序、来源白名单和
   输入总预算继续生效，助手只读上下文不能作为用户证据。
3. **尚未填写回答时，已生成问题被站内缓存清除。** 恢复条件现在包括问题及任务引用；
   通过报告链接返回原补充目标，即使 URL 不带 task 参数，也能恢复已生成的问题和原任务。
   使用当前会话内存，不自动提交、确认、重复生成任务或写入浏览器持久存储；原有会话
   结束清理及目标隔离保留。

## 先复现，再验证

- 新增后端回归在未改逻辑上为 **9 failed / 99 passed**：同名肯否、证书进度与独立备选
  引用暴露 same_fact 问题；7/12 轮真实 SQLite→JobStore→Worker→GatewayIntake 捕获请求，
  暴露用户和助手历史被各截剩 5 条的问题。
- 新增真实 FollowUpWorkspace + MemoryRouter/Routes + StrictMode 回归在未改产品逻辑上
  为 **1 failed / 9 passed**：生成并显示问题后，从报告的新链接返回，问题丢失。
- 修复后上述后端两文件 **108 passed**，补充页组件文件 **10 passed**。回归同时确认
  profile/same_fact 一致、来源引用及档案不改写、不跨事实拼接、不误伤独立备选，恢复时
  不重复发送模型任务、不重新读取已应用档案、不自动保存/确认/诊断。

补充页测试统一 5 秒异步查询窗口及 15 秒用例时限，为真实路由与结果读取的多次更新提供
等待空间，未提高产品请求超时或添加重试。修改后本机默认并发全套通过；未在本轮执行
Windows 实机复验，不能据此宣称 Windows 时间相关问题已彻底消失。

## 完整验证

- 后端全量：**1143 passed、0 skipped、1 warning**；专用一次性 PostgreSQL、队列隔离
  集群及 SQLite，合成资料/fake 模型。原有 pypdf 版本冲突 4 项及新 ZIP + 独立运行环境
  8 项也实际执行，已计入总数，不另行累计。
- 前端默认并发单元：**106 passed**；类型检查、TypeScript/Vite 构建通过。
- 契约：41 schemas、4 examples、18 业务路由，pending=[]；Ruff、格式、diff 检查通过。
- QA-03 轻量浏览器 **8 passed**（本地真实 FastAPI/UI，合成端口/fake 模型）；既有主
  浏览器流程 **16 passed**（mock 与受控 HTTP）。两套均为本轮重新执行，不引用旧成绩。

唯一后端 warning 为既有 Starlette/httpx 弃用提示。没有真实付费模型调用、Windows 实机
或线上部署，没有执行 QA-03 正式数据库浏览器套件。无需 SQL 迁移，未改既有提示版本
和模型预算；#74 的非阻塞运维建议不在本轮范围。

日志和实际归档包位于本地忽略目录 `output/pr69-d-followup/`，其中全部资料为合成测试
素材，不提交原始用户资料或模型凭据。此前验证见 [上一轮记录](pr69-post73-review.md)。

## 本地证据指纹

以下文件位于忽略目录 `output/pr69-d-followup/`，不提交原文或运行凭据。

- `backend-before.log`：`b1551d00b61f2907687733d776ad4fc434bd22ea982fad70d2ead98bf745a840`
- `frontend-before.log`：`42bdc0d86323107c69f8f5e4be2de0a0e04279c5ac965651becdd8204010fe85`
- `backend-final.log`：`a60b8dfd7cdeb024dce7b423fe27ba9cb7fa5702e08f5a4e45511dd7021fc46e`
- `frontend-final.log`：`3f673c5315c6c9dc475fcf6b32648f57f9ab09555939b497e317e1f65456ad23`
- `browser-final.log`：`af5530788a67f7e5373b0683c9cdcff916eb596d043b118b060f1b40efd7b7a6`
- `contracts.json`：`33742bbc38eacc5412394143ab5345ebc68c27d9dfbc7e705b7338f582149a5e`
- `resumedoctor-pr69-review.zip`：`65cb66f8cd4fdbf5214c4dc51024df07e8727706c14c72854d8488e6bbe65736`
