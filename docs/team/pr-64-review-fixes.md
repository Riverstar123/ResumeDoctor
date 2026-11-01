# PR #64 评审修复

日期：2026-11-01。基于 `37b01688fd3f25d9e7c7cf477c225bb18b3e2c2b` 修复 C、E、D 的三项评审意见，详见 [D 的独立评审](https://github.com/Riverstar123/ResumeDoctor/pull/64#pullrequestreview-5726948577)。

## 修复

- **Windows 默认编码**：评分重放 fixture 显式按 UTF-8 读取。用 `PYTHONUTF8=0` 验证，文件默认编码为 cp936，不依赖全局 UTF-8 开关绕过问题。
- **有来源的事实纠正**：profile/chat 提示明确保留旧证据，但允许用户用新增来源更新对应事实并保持 ID；不为统一标签改写旧事实，也不通过追加相反事实保留已被更正的肯定断言。profile/chat 同步升级为 v3，目录版本映射同步；job/report 继续为 v2，原有验收材料及历史快照保持各自记录的版本。
- **整次调用截止时间**：真实网关从调用入口建立单调时钟截止时间，HTTP 请求仅使用剩余额度；网络、JSON/Schema、截断及报告语义修复共用原来的一次重试预算。外层超时覆盖退避和 HTTP，成功前及错误退出时检查时间，避免同步校验耗尽预算后仍返回成功。超时只记录一次 MODEL_TIMEOUT，外部取消保持 CancelledError。

新加 13 个回归场景：五类失败的退避超时、格式/语义修复的剩余 HTTP 预算、两种同步校验超时、调用方取消、ReportService 总时限，以及 chat/document 两条路径的有来源技能纠正。既有无新来源、无关来源、伪造 quote 的拒绝用例继续执行。

## 本轮验证

- Windows / Python 3.12.13 / PostgreSQL 17.11 / Node 24.20.0。后端使用当前 PR 的独立锁定依赖环境；所有数据库、上传材料和 worker 夹具为专用合成测试数据。
- 默认 Windows 编码：`PYTHONUTF8=0`，`locale.getencoding() == "cp936"`；**879 tests collected**。`PYTHONIOENCODING=utf-8` 只用于日志编码，不改变 `Path.read_text()` 的默认文件编码。
- 完整后端：**879 passed / 0 skipped / 0 failed**，Windows 默认 cp936 文件编码，专用已迁移 PostgreSQL 与队列隔离夹具；最终整套运行耗时 282.10 秒。
- 正式 QA-03：**5 passed**，真实 app.database / PostgreSQL / 独立 worker / 浏览器；模型使用登记合成替身。覆盖 PDF、DOCX、两轮对话、五岗位评分、Markdown 导出、模型切换、partial/score_only 与撤销后的零写回。
- 原评审独立边界脚本：**3 passed**，其中曾失败的 ReportService 总时限反例现在得到 MODEL_TIMEOUT；仓库内对应回归为 `tests/llm/test_semantic_repair.py::test_report_semantic_repair_cannot_reset_the_total_deadline`。
- Ruff、格式、契约和 diff 检查通过。契约仍为 36 schemas / 4 examples / 18 已实现业务路由，pending=[]。

复现时将 RD_TEST_DATABASE_URL 指向专用已迁移且名称含 test 的数据库；队列隔离与正式 QA-03 的临时根目录使用较短的 ASCII 路径，避免 Windows PostgreSQL socket 路径长度限制。第一次正式 QA-03 在启动阶段遇到这一环境限制，缩短本轮临时目录后全套通过。中途重启测试时曾连带停止专用主测试库，恢复集群后从头重跑完整后端套件；这两类中断属于本轮测试环境，不作为产品缺陷或成功回归计数。

本轮没有调用付费模型；原合成真实模型证据仍对应修复前的 v2 提示，本轮结果只证明上述回归与修复边界，不将旧真实调用计为 v3 的实测。评分算法、HTTP 字段和数据库结构均未改动；保留原评审状态，供独立复审。
