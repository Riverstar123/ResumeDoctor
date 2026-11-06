# PR #71 整合验证（2026-11-06）

将 #71 `24bab8a` 与 main `b8d93e9` 整合，后者已含 #69 和 #73。用户明确授权协调、整合并合并；本记录只描述本机实际验证，不代表线上部署。

## 冲突处理

- `prompts.py` 和 `catalog.py`：保留主分支的档案、定向追问、结构化条件和报告版本；将工具应用拆分规则加入现有 JD 提示，统一为 profile-v5 / chat-v8 / **job-v4** / report-v7。独立审核仍为 report-grounding-v6，模型目录仍为 models-v4。
- `validation.py`：保留组合条件校验及独立技能拆分，再执行有界工具应用规范化和既有重复项合并。真实备选、证书、学历、到岗条件及忽略状态冲突规则不被工具去重覆盖。
- 两个编辑器：在现有字段外加入摘要折叠，保留证书/到岗事实、属性与组合条件编辑、学历状态定位、保存后确认及常驻操作栏。新增空行和校验失败的字段自动展开。
- 保留 #71 已修复的不可回退匹配和单次调用内的原文解析复用，原评审的长空格、重复动作及长工具名性能回归继续执行。
- 增加组合条件与工具去重联用、证书属性折叠后编辑、OR 条件编辑保存的回归；既有前端测试同步真实展开操作和自动展开行为，没有删除原校验断言。

## 验证结果

本机 macOS、Python 3.12.13、Node 24.14.1、Chromium。资料均为合成数据，模型均为 fake。

| 检查 | 结果 | 本机记录 |
|---|---|---|
| 后端全量 `pytest backend/tests -q --maxfail=5` | **1183 passed，0 skipped**；一条既有 Starlette 弃用提示 | `output/pr71-integration/backend.log` |
| 前端 `npm test` | **114 passed** | `output/pr71-integration/frontend.log` |
| `npm run types:check`、`npm run build` | 通过 | 同上 |
| QA-03 真实 FastAPI + fake 浏览器流程 | **8 passed** | `output/pr71-integration/browser.log` |
| 主浏览器流程（mock / HTTP transport） | **17 passed** | 同上 |
| 契约检查 | **41 schemas、4 examples、18 业务路由，pending=[]** | `output/pr71-integration/contracts.json` |
| Python Ruff/格式、修改前端格式、diff 空白检查 | 通过 | `output/pr71-integration/ruff.log` 及检查输出 |
| 发布包生成 | **82 个运行文件**，HTTP 前端构建通过 | `output/pr71-integration/package.log` |

后端全量已启用独立迁移的 PostgreSQL 测试库、并发/队列隔离、旧版 pypdf wheel 优先级检查，以及独立运行环境中的 SQLite 发布包/worker 验收。对应开关为 `RD_TEST_DATABASE_URL`、`RD_AI03_PG_HOME`、`RD_AI03_ISOLATION_ROOT`、`RD_PARSER_OLD_PYPDF_WHEEL`、`RD_SHOW_ARCHIVE_ZIP` 和 `RD_SHOW_ARCHIVE_PYTHON`；均使用一次性测试资源，不连接业务数据库。

浏览器检查涵盖上传/对话、版本保存确认、双岗位评分、证据与导出、失败降级、会话删除，以及 26 条事实下的摘要、键盘展开、常驻确认按钮、隐藏错误定位和修改保留。部署包检查包含合法/损坏 PDF、DOCX 及两种依赖布局。

未执行 Windows、真实供应商输出或线上验收；本次未发布到学院网站。有限句式规范化不能保证所有真实模型回复都不存在重复要求，旧岗位须重新提取或编辑形成新版本。
