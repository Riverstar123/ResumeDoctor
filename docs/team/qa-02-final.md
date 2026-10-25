# QA-02 最终验收与分支同步

日期：2026-10-25。对应 [Issue #25](https://github.com/Riverstar123/ResumeDoctor/issues/25)、
[PR #57](https://github.com/Riverstar123/ResumeDoctor/pull/57)。C 的原始任务、测试和历史记录保留；
用户本轮明确授权 A 解决原分支冲突、更新记录、检查并在通过后合并。以下最终执行者是 A，
不把 A 的命令或结果记为 C 执行，也不虚构 D 已评审。

## 结论与验证对象

正式 PR 分支的本轮相关验收通过，未发现遗留业务阻塞。这里的“通过”仅指下述合成资料、
fake 模型与 HTTP stub 的边界，不代表真实 AI 或完整浏览器到数据库的安全验收。
提交、推送、最终评审、合并与 Issue 关闭以 GitHub 实际记录为准，不能由本文件推断已完成。

- 原 #57 提交：`2ee25e44a7c7e28ba662925a1778cff9e2a55b8d`。
- 合入 main：`a1947243105c3938e42492a9f48d000c4440b606`，已包含 #55 和 #58。
- QA25-01：E 的 #58 已修复；C/A 对修复代码的批准见 [#58 评审](https://github.com/Riverstar123/ResumeDoctor/pull/58)。本轮 A 在合入后的原 PR 分支重跑，不再仅依赖隔离副本。
- 只解决两处机械冲突并更新验收文档；没有新增业务算法、修改 Schema、锁文件或数据库迁移。

## 冲突处理

`Makefile` 同时保留 INT-02 的数据库 `dev`、显式 `dev-synthetic`、五个 `test-db` 文件，
以及 QA-02 的 `test-security` 和 PHONY。`docs/07-testing.md` 同时保留两阶段记录，
更新 #55 已评审合并与 QA25-01 已修复的当前状态。

首轮 `qa-02-results.json`、二次 `qa-02-recheck-results.json` 保留原始数值与当时的待修状态；
这两份历史结果不作为最新状态。当前结果另存 [qa-02-final-results.json](qa-02-final-results.json)。
`qa-02.md` 已更新当前结论，旧复现与修复过程继续保留。

## 实际执行

| 检查 | 本轮实际结果 |
|---|---|
| `make test-security UV='/opt/homebrew/bin/uv --no-config'` | 754 passed，0 failed，0 skipped；32.70 秒；本轮独立、已迁移 PostgreSQL |
| 原安全浏览器配置、已安装 Edge | 4 passed；3.7 秒；API 全为 HTTP stub |
| `ruff check backend` / `ruff format --check backend` | 通过；113 个 Python 文件 |
| 契约检查 | 36 schemas / 4 examples / 18 业务路由，pending=[] |
| `npm run types:check`、`npm run build` | 通过 |
| 安全配置/用例 TypeScript、Prettier | 从 `frontend/` 执行，通过 |
| 与此前隔离组合副本比较 | 163 个已跟踪 backend/frontend 文件和 Makefile 字节相同；不是用旧副本结果冒充本轮重跑 |

Python 环境来自项目锁文件并启用 database extra。`uv --no-config` 只避开本机用户级镜像配置，
没有更新锁文件或更改依赖版本。浏览器沿用项目已有安全入口，不创建新测试文件或增加付费调用。

## 验收条目 → 文件/证据 → 结果

| 条目 | 文件/证据 | 结果与边界 |
|---|---|---|
| T02 异常文档、展开限制、路径穿越 | `tests/intake/test_documents.py`、`tests/platform/test_security_acceptance.py` | 真实生成 PDF/DOCX、解析失败安全返回，无伪造档案；完整回归包含其中 |
| T15 跨会话读取/修改/导出 | `tests/platform/test_security_acceptance.py`、既有平台隔离回归 | 真实 PostgreSQL 与 HTTP 边界，另一会话 404；本人内容与导出不变 |
| T16 删除/到期后迟到模型结果 | 同一安全集成文件及 `tests/platform/test_jobs.py` | 在真实解析后放行迟到结果，验证禁止写回与文件清理；到期分支保留有效租约再检查会话有效性 |
| T17 提示/数据、评分与引用边界 | `tests/intake/test_security_acceptance.py` | 真实 M3/M4/M5 加受控模型输出；不改分、不接纳伪造引用，不代表真实模型抵抗所有攻击 |
| 原件终态/24h 兜底、七天会话清理 | `tests/platform/test_postgres.py`、Worker 回归 | 真实 PostgreSQL 与受控时间，不把用例通过称为持续运行七天 |
| QA25-01 长输入、相邻邮箱、Unicode、副本隔离 | `tests/reporting/test_privacy.py`、`tests/reporting/test_service.py`、M3 资源回归 | 合入后通过；长输入由独立子进程六秒 watchdog 约束，过滤保持冻结输入不变 |
| 日志与错误脱敏 | intake/platform 安全集成中的 app.* DEBUG 捕获、合成原文/密钥/路径标记 | 场景内无泄露；本轮未重复故意注入的历史实验 |
| HTML 页面与 404 清空 | `frontend/tests/e2e/security.spec.ts` | 四项真实浏览器检查通过；服务端响应由 stub 提供，后端隔离证据来自独立 PostgreSQL 用例 |

完整 754 项包含表内用例，不将子集数量另加到总数。
Markdown 保证转义原始 HTML，未验证所有外部阅读器的链接/远程资源策略；
DOCX 排版页数未核验的既有告警保留。有限联系方式过滤不是完整匿名化，非 fake 仍需显式隐私策略。
本轮未调用真实供应商、不声称 T22/AI-03 通过，也不把浏览器 stub 视为完整真实服务端端到端。

## 本地证据与收尾

命令日志在工作树 `output/pr57-final/`，均为本轮合成资料，不加入提交。
正式提交前核对 diff、暂存清单、冲突标记、私有 `/指南.md` 忽略规则及其未被跟踪的状态。
仅更新原 PR #57，不自动开始下一 Issue；#25 在验收发布与合并前保持 OPEN。
