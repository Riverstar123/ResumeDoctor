# PR #64：合成资料真实模型探索测试

日期：2026-11-01。维护者明确授权生成虚构简历、经历和 JD，真实测试并修复后更新 PR #64。本目录只包含合成材料，未复用用户原来的档案或失败报告。

## 测了什么

[inputs.json](inputs.json) 给出完整原文：计算机本科、明确起止的实习、实际使用 Python/SQL/JS、仅了解 Excel、明确不会 Docker；未提及 Kubernetes。岗位分别检查技能与学历、partial/unmet/unknown、经历月数与技能别名；另用同一句中的 Python 和 SQL 检查独立要求拆分。

真实路径为文字 PDF / DOCX 上传、自然语言对话 → 用户确认 → JD 提取与确认 → PostgreSQL 队列和独立生产 worker → M4 确定性评分 → 真实模型报告 → 网页与 Markdown 导出。服务使用独立 test 数据库及上传目录；浏览器与 API 分别在 5260/8060，未覆盖用户 5173/8000 的会话资料。

实际模型：DeepSeek 官方 `deepseek-flash`（`real-default`）与智谱 BigModel 官方 `glm-5.3`（`real-model-b`）。本轮没有使用 fake 结果冒充真实模型验收。

## 发现、原因和修复

| 问题 | 修复与可核对证据 |
|---|---|
| 明确实际应用的 Python/SQL 被抽成 skill，导致只获 partial；“数据分析实习”也未匹配“数据分析”领域 | M3 v2 提示使用原子应用事实与领域标签，保留原文证据、项目事实及实习身份。未修改 matcher-v1/coverage-v1。比较 [修复前档案](before/profile-pdf.json) 与 [修复后档案](after/profile-pdf.json)。 |
| 报告改写借用其他证据的日期，或模板中出现原文不支持的“一个” | 严格提示逐条数字引用约束；把对应评分允许的 gap 引用显式提供给模型；业务校验失败可在原网关共享重试预算内修复。保留 [原始合成报告](before/raw-synthetic-reports.json) 和 [基线诊断](before/diagnosis.json)。没有放宽报告校验或为成功伪造数字。 |
| GLM 正文为空且 finish_reason=length | 初始 [GLM 结果](after/diagnosis-glm-before-low.json) 三岗均仅评分；供应商返回成功 HTTP，但思考耗尽输出预算。仅将实际型号 glm-5.3 的 reasoning_effort 配为 low，目录版本升至 models-v3；其他型号不追加参数。依据：[智谱 GLM-5.3 官方说明](https://docs.bigmodel.cn/cn/guide/models/text/glm-5.3)。 |
| GLM low 的一次中间复测仍有越界 gap 引用/引用未支持数字 | 如实保留 [中间结果](after/diagnosis-glm-low-initial.json)，随后补充 gap_constraints 与修复反馈，再完整复测。 |
| 对话模型把学历 value 返回“本科学位”，被业务枚举拒绝 | [实际错误输出](before/chat-invalid-education.json) 可离线核对；chat-v2 明示学历英文枚举与非学历 value=null。新一轮网页对话成功，见 [web-chat.json](web/web-chat.json)。 |
| UUID 中恰有手机号数字段时，隐私过滤破坏 source/evidence 引用，偶发 UNKNOWN_SOURCE | 保留符合 UUID 形状的标识；普通手机、邮箱及伪装成 source_id 的裸手机号仍过滤。增加确定性 UUID 回归与原对象不可变断言。 |
| MODEL_OUTPUT_INVALID 的 422 被网页提示成“检查输入字段” | 按错误码优先提示，增加白名单原因类别，帮助区分结构、截断、数字与引用。不把原始输出、推理内容或供应商错误暴露到页面和日志。 |
| 终态任务刷新后“等待时间”继续增长；真实导出总标题误写演示数据 | 终态按保存的 updated_at 计算处理耗时；总标题改为中性 ResumeDoctor，fake 单项仍保留明确标识。 |

## 真实结果

以下数字全部来自本目录保存的完整 DTO；分数表示材料覆盖度。

| 场景 | 基线 DeepSeek | 修复后 DeepSeek | 同一冻结快照 GLM 最终复测 |
|---|---|---|---|
| Python、SQL、学历 | 66.7，仅评分 | 100，完整报告 | 100，完整报告 |
| Excel / Docker / Kubernetes | 20，仅评分 | 20，完整报告 | 20，完整报告 |
| 至少 24 月经历 / JavaScript | 16.7，完整报告 | 66.7，完整报告 | 66.7，完整报告 |

来源：[基线](before/diagnosis.json)、[DeepSeek 最终](after/diagnosis.json)、[GLM 最终](after/diagnosis-glm.json)。不是为了提高分数修改评分算法：变化来自新一轮提取的事实/要求；旧冻结档案及报告不自动重写。同一修复后快照切换两模型时，完整 ScoreResult 逐字段相等，先前保存的 DeepSeek 报告也保持原样。mixed 场景仍为 Excel=partial、Docker=unmet、Kubernetes=unknown。

网页对话与 DOCX 各自都完成档案确认、复合 JD 三项要求、成功诊断（100）、处理中刷新恢复、一次诊断提交及实际下载。DOCX 正常展示 DOCX_PAGINATION_UNVERIFIED，未伪称已验证排版页数。见 [对话 DTO](web/web-chat.json)、[DOCX DTO](web/web-docx.json)、[对话等待截图](web/chat-progress.png)、[对话报告](web/chat-report.png)、[DOCX 档案](web/docx-profile-final.png)、[DOCX 报告](web/docx-report.png) 与 [390×844 手机宽度截图](web/docx-report-mobile.png)。手机页面无横向溢出。报告下载见 [对话 Markdown](web/chat-report.md)、[DOCX Markdown](web/docx-report.md) 及 [双模型导出](after/report-glm.md)。

[provider-summary.json](provider-summary.json) 是隔离测试进程记录的供应商请求摘要，含本轮初始失败、中间复测及最终结果，共 35 次 HTTP 请求；只保留供应商域名、模型目录 ID、任务类型、HTTP 状态、finish_reason、usage 和输出长度，不提交原始思考内容、请求头、会话 Cookie 或密钥。其中两次 DOCX 上传是测试浏览器连接恢复后的重复素材验收，不是应用重复提交诊断。任务是否成功以 DTO 业务状态为准，不能把 HTTP 200 当作报告成功。

## 回归与复现

[checks.json](checks.json) 记录本轮验证：完整后端 866 passed / 0 skipped；前端组件 44 passed；主浏览器 16 passed；轻量 QA-03 8 passed；真实 PostgreSQL + 独立 worker 的正式 QA-03 5 passed。回归套件用 fake/stub，和上面的真实付费调用分开计。build、OpenAPI types、Ruff、契约校验与 diff 检查通过。契约仍为 36 schemas、4 examples、18 已实现业务路由、pending=[]。

离线重放已保存的真实提取快照，无需密钥和网络：

```sh
cd backend
uv run --frozen --extra database pytest tests/scoring/test_exploratory_real_snapshot.py tests/intake/test_reference_privacy.py tests/llm/test_semantic_repair.py
```

完整后端需专用已迁移的 PostgreSQL 测试库，并给真实数据库 E2E 夹具配置 RD_AI03_PG_HOME 与隔离根目录；不能把 RD_TEST_DATABASE_URL 指向日常使用库。浏览器本轮用隔离端口避开已有应用。运行规范见 [开发环境](../../../08-development.md) 与 [模型配置](../../../10-model-configuration.md)。

真实复现时，从 inputs.json 制作文字 PDF/DOCX 或复制经历描述，选择 DeepSeek，核对提取内容后确认，再依次录入三个 JD。诊断完成后在报告页切换 GLM 并用当前快照重新诊断，核对评分与历史报告。该步骤会发送合成材料到对应官方供应商并消耗账户额度，回归测试本身不会调用这些供应商。

环境：macOS arm64、Python 3.12.13、PostgreSQL 18.4、Node 26.0.0、npm 11.12.1；与固定 PG 17.11 / Node 24.14.1 有差异，本轮未完成 Windows 验证。有限合成样例通过不代表模型今后不会再产生无效输出；失败仍应保留评分、限制修复次数并给出准确提示。报告仍上限 3,000 输出 token、每次报告调用总计 45 秒，网络/格式/业务修复共享最多一次重试，不为本轮成功而延长预算。

文件完整性见 [manifest.json](manifest.json)。本目录没有真实用户简历、会话凭证或原始推理日志。
