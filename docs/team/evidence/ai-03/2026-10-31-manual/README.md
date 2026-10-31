# 2026-10-31：维护者独立真实网页验收

本目录为维护者本机已完成的验收原始证据，业务代码基线 `1f0993271ff2d2444b737431695c74c271cbdf12`（PR #60 合并后）。使用 macOS / Python 3.12.13 / PostgreSQL 18.4 / Node 26.0.0；全部输入为登记合成 PDF 和单个 Python JD，没有真实个人资料。

实际链路：真实浏览器 → Vite HTTP 代理 → `app.database` → 专用 PostgreSQL 队列 → 独立生产 worker → 两家官方供应商。观察器仅记录 HTTP 状态、公开模型名、usage、耗时，不保存请求头、提示词、模型原始正文或密钥，也不改变请求参数和校验逻辑。

| 场景 | 证据 | 实际结果 |
|---|---|---|
| DeepSeek 网页提取和报告 | `01-diagnosis-deepseek.json`、`01-report-deepseek.md` | `real-default / deepseek-flash` succeeded，评分 50.0；档案 4 条事实、3 条证据 |
| GLM 同快照重新生成 | `02-diagnosis-glm.json`、`02-report-glm.png`、`02-report-glm.md` | `real-model-b / glm-5.3` succeeded；相同 Profile/Job id+version，完整 ScoreResult 深度相等 |
| 历史报告保持不变 | `01-diagnosis-deepseek-reread.json` | 与切换前 DeepSeek JSON 完全相等；GLM 报告刷新后可读取 |
| 真实供应商错误降级 | `03-diagnosis-degraded.json`、`03-report-degraded.png`、`03-report-degraded.md` | 不存在型号真实返回 HTTP 400；公开 MODEL_UNAVAILABLE、score_only、评分仍完全相等，仍可网页导出 |
| 未知公开 model_id | `04-invalid-model-id.json` | 422 / MODEL_UNAVAILABLE，不回退其他模型 |
| 切回 fake | `05-fake-catalog.json`、`05-fake-diagnosis.json`、`05-fake-rollback.png` | 页面恢复演示标记、仅 demo 目录，新报告 succeeded / fake / synthetic-fake-v1；无新增供应商调用 |

故障型号只通过验收启动器的进程变量启用，随后顺序重启同一 API/worker 配对，复用同一冻结快照；没有不同配置的 worker 同时争用一个队列。fake 回退同样只覆盖测试进程，维护者私有 `.env` 保持原样。

`provider-results.json` 为本次收到的 13 条 HTTP 结果（12 条 200、1 条预期 400）。已收到 usage 的 DeepSeek 总量为 25,767 tokens（输入 20,041、输出 5,726）；GLM 总量为 4,576 tokens（输入 2,509、输出 2,067）。这些包含最初自动套件失败之前已完成的请求。首轮测试中断时另有在途报告没有最终 usage，因此这不是最终账单或全部可能计费量。GLM 成功请求耗时 28.946 秒。

官方费用/限额核对（2026-10-31；实际扣费与专属限额以账号为准）：

- [DeepSeek 定价](https://api-docs.deepseek.com/quick_start/pricing/)：Flash 低峰每百万 tokens 缓存命中输入 / 未命中输入 / 输出 USD 0.003 / 0.15 / 0.6，周末低峰；[账户并发说明](https://api-docs.deepseek.com/quick_start/rate_limit/)列 Flash 2500。本次已知命中/未命中输入为 8,832 / 11,209，已知用量按该价约 USD 0.00514。
- [智谱定价](https://docs.bigmodel.cn/cn/guide/start/pricing)：GLM-5.3 每百万 tokens 输入 / 输出 / 缓存命中人民币 8 / 28 / 2 元；本次 cached_tokens=0，已知用量约人民币 0.07795 元。[限流说明](https://docs.bigmodel.cn/cn/api/rate-limit)明确账户与模型权益各有不同。未访问维护者账户后台，不能声称核实其专属配额或余额；本次收到结果中无 429。
- 两种币种分别记录，金额为响应 usage 的估算，不是账单查询结果，也不包括未知在途请求。

最初原始 AI-03 套件实际为 1 failed / 1 did not run：五岗位尚在处理时，共享 fake helper 的 20 秒等待先退出。本目录证明独立单岗位真实网页流程通过，不把该原始套件写成通过；等待整改后的完整五岗位自动结果另在上级验收文档记录。
