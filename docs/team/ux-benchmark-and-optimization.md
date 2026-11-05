# ResumeDoctor：GitHub 对标与优化大纲

核对日期：2026-11-05。评分依据为用户提供的课程截图：**项目完整度、新颖性、AI 能力展现**。截图没有分项权重，因此本文不估计加分数或最终成绩。

本轮先对照项目规划和现有实现，再检查外部仓库的具体代码，落地适合当前版本的体验改进。本记录描述本地开发与验证成果；发布 PR 不代表已合并或替换学院服务器上的版本。

## 1. 现有基础与本轮取舍

项目已有上传/对话建档、事实及来源核对、版本确认、多个岗位独立诊断、逐要求证据、建议与行动、历史报告及同快照模型对比。评分由确定性规则计算，AI 负责提取、追问和报告解释；缺少材料与明确不满足分开处理。

对应本地依据：`frontend/src/pages/`、`backend/app/scoring/matcher.py`、`backend/app/reporting/`、`docs/06-ai-contract.md`、`frontend/README.md`。源码核对、本地测试和有限真实模型烟测分别记录，不代表已验收线上服务器。

| 评分维度 | 对标时的具体问题 | 本轮本地实现 | 后续验证与迭代 |
| --- | --- | --- | --- |
| 项目完整度 | JD 确认与诊断按钮相距远；长页面反复滚动；缺少深色模式 | 统一主题、常驻操作区、错误定位、手机布局 | 在部署版本上补做完整发布检查 |
| 新颖性 | 已有来源和版本机制，但补充经历到再次诊断的路径仍分散 | 修改清单、岗位定向追问、新确认档案与原 JD 再诊断、前后变化比较 | 用真实供应商与固定材料验证完整操作链 |
| AI 能力展现 | 引用存在不等于全文语义有依据 | 非 fake 报告独立事实审核、确定性来源规则与合成边界测试 | 扩展人工标注案例，记录真实模型误放行与误拒绝 |

深色模式与操作栏主要补齐使用体验。建议把课程展示的核心放在 AI 如何帮助用户找到真实材料、形成可核查的修改，以及修改后发生了什么变化。

## 2. 选定仓库与深入调研

筛选优先级是机制与本项目的适配程度、是否有可读实现、能否保持事实确认边界。没有使用星数作为质量证明，也没有运行外部仓库或导入其依赖。

### Reactive Resume

核对版本：`a4a4d49adbe9da44f546a950f958b54b4393aca7`。

- [ThemeProvider](https://github.com/reactive-resume/reactive-resume/blob/a4a4d49adbe9da44f546a950f958b54b4393aca7/apps/web/src/features/theme/provider.tsx)：分开保存用户偏好与实际主题，订阅系统主题变化，统一应用到根节点。
- [修改提案](https://github.com/reactive-resume/reactive-resume/blob/a4a4d49adbe9da44f546a950f958b54b4393aca7/packages/resume/src/proposals.ts)：保留 before、after、why 和状态；应用前检查原文/结构快照，识别过期建议。
- **采用**：浅色/深色/系统三种偏好；建议先审阅；切换报告或建议变化后清空旧选择。
- **舍弃**：完整简历编辑器、服务端主题 cookie、路由与周边依赖。本项目的修改清单只汇总文字，不自动写回事实档案。

### Reseno

核对版本：`609360b7941d777812f136d18da0eaba9fa36bc1`。

- [主题实现](https://github.com/J0EY0/Reseno/blob/609360b7941d777812f136d18da0eaba9fa36bc1/frontend/src/lib/workspace-theme.ts) 与 [首屏测试](https://github.com/J0EY0/Reseno/blob/609360b7941d777812f136d18da0eaba9fa36bc1/frontend/tests/theme-bootstrap.test.ts)：首次渲染前应用主题，处理存储不可用，并同步原生控件的 `color-scheme`。
- [常驻工作区头部](https://github.com/J0EY0/Reseno/blob/609360b7941d777812f136d18da0eaba9fa36bc1/frontend/src/components/workspace/resume-detail-workspace-header.tsx) 与 [高度测量](https://github.com/J0EY0/Reseno/blob/609360b7941d777812f136d18da0eaba9fa36bc1/frontend/src/components/workspace/resume-detail-workspace-view.tsx)：操作保留在可达位置，并根据实际高度处理后续区域的偏移。
- **采用**：首屏主题初始化、存储失败回退、动态测量操作区高度。ResumeDoctor 改为底部常驻区域，集中保存、确认和诊断。
- **舍弃**：整套工作区布局替换；保持现有页面与业务状态管理。

### Resume Matcher

核对版本：`d480551798b7aa97f5b57ba1972ee383bd882238`。

- [分章节问答与合并](https://github.com/srbhr/Resume-Matcher/blob/d480551798b7aa97f5b57ba1972ee383bd882238/apps/backend/app/services/resume_wizard.py)：结合当前草稿推进问题，只更新当前章节；跳过步骤时保留草稿，最终由用户确认。
- [问题卡片焦点](https://github.com/srbhr/Resume-Matcher/blob/d480551798b7aa97f5b57ba1972ee383bd882238/apps/frontend/components/resume-wizard/question-card.tsx)：用用户是否已操作控制后续焦点转移。
- **采用**：明确当前步骤、针对用户操作定位下一处内容；按本项目事实来源契约实现岗位定向追问。
- **舍弃**：技能分支将 `inferred_skills` 合并到结果的做法。ResumeDoctor 的技能必须关联用户来源，并经确认后用于诊断。

### DaveVoyles/resume-builder

核对版本：`33b9da7a38436b59e04a0d04bed00ca1d1dba182`。

- [候选证据匹配](https://github.com/DaveVoyles/resume-builder/blob/33b9da7a38436b59e04a0d04bed00ca1d1dba182/src/core/possible-matches.js)：用相关词和词语重叠寻找可能的材料，产生待用户判断的建议，不直接写入简历。
- [缺口行动分类](https://github.com/DaveVoyles/resume-builder/blob/33b9da7a38436b59e04a0d04bed00ca1d1dba182/docs/playbooks/gap-analysis.md)：区分表达、证据、相邻技能等缺口并组织下一步。
- **采用**：把缺口转成用户能核对的具体动作，候选材料必须经确认。
- **舍弃**：把未提及、又无相关词的要求归为真实能力缺口；也不把词表匹配描述为经过验证的语义理解。继续保留 `unknown ≠ unmet`。

本轮按本项目接口和状态管理独立实现设计模式，未复制外部实现。固定版本许可证：[Reactive Resume / MIT](https://github.com/reactive-resume/reactive-resume/blob/a4a4d49adbe9da44f546a950f958b54b4393aca7/LICENSE)、[Reseno / MIT](https://github.com/J0EY0/Reseno/blob/609360b7941d777812f136d18da0eaba9fa36bc1/LICENSE)、[Resume Matcher / Apache-2.0](https://github.com/srbhr/Resume-Matcher/blob/d480551798b7aa97f5b57ba1972ee383bd882238/LICENSE)、[DaveVoyles / MIT](https://github.com/DaveVoyles/resume-builder/blob/33b9da7a38436b59e04a0d04bed00ca1d1dba182/LICENSE)。

## 3. 本轮已实现

### 外观模式

- 顶部可选浅色、深色、跟随系统，默认跟随系统。
- 在首屏样式加载前解析主题，减少深色偏好下的闪白；浏览器原生表单和主题色同步。
- 只存储 `rd:theme` 枚举，不增加个人资料缓存。存储失败时当前页仍能切换。
- 使用统一语义色适配输入、状态、证据、报告、弹窗及焦点；加深浅色辅助文字与输入边框。

实现：`frontend/index.html`、`frontend/src/theme.ts`、`frontend/src/components/Shell.tsx`、`frontend/src/styles.css`。

### JD 常驻操作区

- 同一处完成保存新版本、确认 JD、开始诊断，并可定位岗位列表和当前 JD。
- 移动的是原有操作，不增加重复提交入口。未保存、待确认、忙碌、限流、模型能力、档案确认等门禁继续生效。
- 字段校验失败后聚焦摘要，点击问题可定位字段；API 错误位于操作区附近。
- 根据操作区实际高度预留底部空间，适配窄屏、长岗位名称及错误提示。

实现：`frontend/src/pages/JobsPage.tsx`、`frontend/src/components/JobEditor.tsx`。

### 报告修改清单

- `requires_user_input=false` 显示“可审阅采用”，支持选择、全选、清空、单条复制和汇总复制。
- `requires_user_input=true` 显示待补事实模板；保留原文、模板、理由、证据，不提供将其作为完成稿直接复制的按钮。
- 复制失败提供反馈和可手动选取的文字；等待复制时锁定选择，避免成功提示对应旧内容。
- 选择仅保留在组件内存；切换岗位、报告或建议内容时清空，同内容刷新不重复重置。
- 清单不修改档案、不改变评分。`requires_user_input=false` 也不代表模型表达已经通过完整语义核验。

实现：`frontend/src/components/ReportSuggestions.tsx`、`frontend/src/pages/ReportPage.tsx`。

### 报告事实忠实度审核

确定性校验继续检查要求/证据 ID、缺口与评分对应、原文片段、待补充标记及数字来源。在此基础上，非 fake 报告新增独立模型审核请求，逐项检查 summary、gap、suggestion、action 的完整语义与允许证据是否一致。审核只判断冻结候选，不改写候选；不支持、矛盾、不确定、不完整或引用越界均拒绝报告，已保存评分继续可看。

生成与审核使用同一已选模型、两份独立请求，共享 45 秒总期限和一次失败重试，正常两个 HTTP 请求、最多三个。实质性审核拒绝不重试寻求通过；审核输出被截断也直接结束，不能丢弃已有否定后重问。当前报告提示为 `report-v3`，审核提示为 `report-grounding-v2`，审核上下文保留冻结 JD 但不将其当作用户证据；不支持审核的非 fake 网关拒绝报告。

最初的只读复核表明，仅靠确定性引用校验会接受“SQL 证据支撑 Kubernetes 生产运维”的构造反例；无来源数字则会被拒绝。这是增加语义审核的原因，不是线上事故记录。新增 `grounding` 与网关测试使用合成候选和审核结果检查放行/拒绝边界，不能据此推算真实模型准确率。

fake 路径只执行确定性检查，不运行独立语义审核，也不提供真实性保证。非 fake 审核本身同样不是事实证明，仍须真实供应商与人工标准复验。

实现：`backend/app/reporting/grounding.py`、`backend/app/reporting/service.py`、`backend/app/llm/openai_compatible.py`。

### 岗位驱动的补充问答

已增加 `diagnosis_focus` 与 `questions_only` 可选消息字段，M2 从同会话诊断读取冻结岗位、非 met 要求与评分约束，M3 按 `chat-v4` 组织问题。浏览器只提交目标标识，不自行声称一段文字属于用户事实。

已实现路径：

1. 在某条缺口旁选择“补充这项经历”。
2. 传递冻结的报告、JD 版本、要求及缺口上下文；服务端验证资源属于同一会话。
3. 首轮 `questions_only=true` 生成问题，档案内容、版本、确认状态不变，不保存 user 消息；允许用户如实说明没有做过。
4. 从用户真实回答提取候选事实并保留原文引用；内容变化形成未确认的新草稿，由用户核对确认。
5. 以新确认档案和原 JD 版本开始新诊断，保留旧报告。

任务结果回显目标，前端恢复时检查归属；旧结果不能自动降回较早档案或覆盖未保存编辑。要求文字和模型问题不作为用户证据，不自动补写未提供的技能。实现涉及 M1/M2/M3 的接口与状态处理，已同步 OpenAPI；没有新增数据库表或迁移。

实现：`frontend/src/pages/FollowUpPage.tsx`、`backend/app/platform/followup.py`、`backend/app/intake/gateway_intake.py` 及平台任务提交路径。

### 解释价值：同一岗位下的前后变化

已新增独立档案版本比较：同一个 profile ID、两个不同已确认版本、相同 JD ID/版本、相同评分与 matcher 版本。逐要求并列显示保存的状态、理由、各自冻结证据；展示材料覆盖分和未知比例差值，不重新计算分数。旧的同快照模型 `Comparison` 保留原条件与独立入口。

按档案版本而非报告创建时间确定前后；新增引用不直接称为新增能力，unknown→unmet 不标为“退步”。资料截止月份变化会提示其对未结束经历月数的影响。JD、规则、档案归属等条件不符时明确拒绝比较，单纯选择/复制建议不产生分数变化。

实现：`frontend/src/components/ProfileVersionComparison.tsx`、`frontend/src/lib/profileComparison.ts`、`frontend/src/pages/ReportPage.tsx`。页面支持 `?before=旧诊断ID&job=岗位ID`，可在新旧报告之间导航。

## 4. 后续验证与迭代

本地实现后的下一步是验证，不将下面的工作写成已经完成：

1. 在已通过的有限真实供应商成功烟测基础上，扩展双供应商网页验收，覆盖审核拒绝、超时及降级；两次请求共用预算，需观察更长资料的延迟。
2. 扩展带人工标准的固定案例，包括未提及技能、明确否认、扩大职责、编造数字和引用与结论不一致；分别记录误放行、误拒绝，不预填通过率。
3. 在实际发布版本上检查完整浏览器与真实供应商操作链；本地数据库、浏览器 mock 和 ASGI HTTP 验证不替代生产部署验收。

### 课程展示建议

用一份合成资料完整展示“输入→确认→核对 JD→诊断→查看证据→岗位定向补充→确认新档案→原 JD 再诊断→比较变化”。保留“确实没有这项能力”的案例，展示明确否认与缺少证据的区别；报告审核展示通过和拒绝两条路径。

展示时标清本地实现与真实验收状态，区分真实模型结果和 mock/fake 合成演示。本轮已修改后端对话与报告实现并通过有限真实供应商烟测，尚未更新学院服务器。

## 5. 本轮验证记录

验证环境使用本机已有 Node 24.22.1，符合 `package.json` 的 `>=24.14.1 <25`；项目 `.nvmrc` 固定的 24.14.1 未被改动。没有安装新应用依赖。

- 前端类型契约漂移、TypeScript、HTTP 构建与格式检查通过；Vitest **90 项**、现有 Playwright **16 项**通过。范围包括主题、JD 门禁、建议复制、定向任务恢复、未保存编辑保护、原 JD 再诊断、跨档案比较及原有流程。见[前端完整日志](../../output/playwright/ai-workflow-frontend-check.log)。
- 后端完整回归 **988 通过、4 跳过**，PostgreSQL 锁/租约/恢复与 AI03 队列隔离实际执行；跳过项仅因缺少展示归档包和独立运行环境。契约检查 **37 schemas、4 examples、18 路由，pending=[]**。见[后端日志最后一轮](../../output/playwright/ai-workflow-backend-full.log)。最后补齐审核 JD 上下文后，再跑 `llm + reporting`，**270 项通过**，这是重叠子集，不与全量结果相加。见[最终审核回归](../../output/playwright/ai-workflow-backend-m5-final.log)。
- PostgreSQL + ASGI HTTP 另完成 **5 组**验收：提问与幂等回放保持档案/确认且不写 user 来源；回答生成草稿并关联实际消息原文；确认后用原冻结 JD 重诊断；无变化回答不增版本；跨会话目标拒绝。真实 M4 将合成案例的 SQL 要求由 partial 改为 met，旧报告与旧档案保持不变。模型端口明确注入合成实现，见[数据库 HTTP 验收](../../output/playwright/ai-workflow-pg-followup-http.log)。
- Playwright CLI 实际操作走通“报告缺口→岗位问题→补充回答→确认新档案→同 JD 新报告→自动比较”，并验证从旧报告进入时读取最新档案。桌面深色与 390 像素手机页面检查通过，无横向溢出。浏览器使用明确标记的 mock；其自定义材料占位评分不能证明真实改善。截图：[深色比较](../../output/playwright/focus-comparison-dark.png)、[手机比较](../../output/playwright/focus-comparison-mobile.png)、[手机定向追问](../../output/playwright/follow-up-mobile-dark.png)。唯一观察到的控制台资源错误为开发预览缺少 favicon，未观察到业务 JavaScript 异常。
- 真实供应商合成烟测使用 `real-default`：报告生成与独立审核 **13.632 秒 / 2 次 HTTP**，规则分数未变；只提问 **2.269 秒 / 1 次 HTTP**，档案逐字段未变；合成回答整理 **5.091 秒 / 1 次 HTTP**，旧证据保留、新证据来自本轮原文。实际联网合计 **4 次请求 / 4 次响应**，无重试。此前受限环境 DNS 失败的 6 次未建连尝试另行记录，不能算作供应商响应。见[真实模型安全摘要](../../output/playwright/ai-workflow-real-smoke.json)。这仅证明三个成功样本可运行，不推算真实性准确率，也不替代真实浏览器全链路与双供应商验收。

未访问线上用户资料；发布 PR 后仍待评审、合并与部署。`output/playwright/` 为本地检查产物，不属于应用部署资源，也不随本轮源码提交发布。首轮体验检查日志和截图仍保留，不能用其旧数量代表本次扩展结果。

## 6. 上传预计毕业与报告长度修复（2026-11-05，PR #69 后续提交）

- 报告生成与审核的每次输出上限由 3,000 提高至 6,000 tokens；提示要求压缩重复说明、建议与行动各优先最多三条，保留所有必要缺口。共享 45 秒截止与一次重试不变；审核截断仍拒绝，不通过重问改变否定结论。长度提示明确说明不是账户余额不足。参数语义见 [DeepSeek 官方接口文档](https://api-docs.deepseek.com/api/create-chat-completion/)。
- M3 提取、M2 保存及前端一致允许已开始的在读教育保存预计毕业月份；保留 completed=false，不改资料截止月，不授予已完成学历，不增加工作月数。工作/项目及已毕业或完成状态未知的教育仍拒绝未来结束日期。表单区分预计毕业月份。
- 档案校验提供日期、学历或引用类别；直接手工编辑仍返回 VALIDATION_ERROR，后台模型结果校验失败返回 MODEL_OUTPUT_INVALID 和安全 reason_code，不把模型错误笼统归咎于用户输入。不修改数据库结构。当前提示为 profile-v4 / chat-v5 / report-v4。

验证结果：

- 完整后端回归 999 通过、4 跳过；跳过项为缺少展示归档包及独立运行环境。PostgreSQL 与 SQLite 测试实际执行。日志为本地 `output/playwright/upload-length-backend.log`。
- 前端类型/构建、93 项 Vitest、16 项既有 Playwright 通过；新增覆盖预计毕业校验、未来日期错误及输出长度提示。日志为本地 `output/playwright/upload-length-frontend.log`。Ruff、格式、diff 与契约检查通过（37 schemas / 4 examples / 18 routes）。
- 新增真实 DOCX 格式的合成上传 → worker 提取 → SQLite 保存 → 确认测试；验证预计毕业日期和原文定位保留。在读硕士不会满足“已取得硕士学位”的要求；模型将未来毕业标为已完成时明确失败。
- 用户附件仅在本地解析，确认日期表达保留；未向外部模型发送附件，未提交原件或内容。附件外部模型测试被自动审批拒绝，已改用独立合成资料。
- 真实模型合成验证：在读教育提取与两层校验通过，预计毕业日期保留且 completed=false。三个独立报告候选中，两个未通过真实性审核，一个完整生成并通过审核；所有报告请求均使用 6,000-token 上限，未观察到长度截断。通过案例的规则评分未变。拒绝结果保留记录，没有放宽审核或重审已拒绝候选。结果不用于推算准确率。安全摘要为本地 `output/playwright/upload-length-synthetic-real.json`、`upload-length-report-real.json`、`upload-length-diagnostic-real.json`。

本次更新 PR，不包含学院服务器部署；原附件的真实模型端到端验收未执行。
