# SQLite 展示站备选：本机验证记录

关联 Issue：#65。测试日期：2026-11-03（北京时间）。该记录不代表线上发布或队友验收完成。

## 初版已执行（d6c6028）

- Python 3.12.13；前端固定 Node 24.14.1 下构建、类型检查和 Vitest 通过。
- 后端全量：892 passed，0 skipped，1 个依赖弃用 warning。使用一次性 PostgreSQL 库，显式设置 RD_TEST_DATABASE_URL、RD_AI03_PG_HOME 和独立 RD_AI03_ISOLATION_ROOT；包含原 PostgreSQL、SQLite、展示入口与队列隔离用例。
- SQLite/展示入口专用：13 passed。覆盖聊天/DOCX → 档案 → 五个 JD → 评分报告/导出 → 新连接读取、跨会话拒读与撤销；独立连接并发幂等/编辑/任务上限；跨进程竞争/异常退出/租约接管/旧结果拒写/任务截止；不可变版本、外键、UTC/原件清理；仅 DeepSeek 目录/缺密钥失败；静态文件隔离、白名单及密钥特征检查、依赖列表一致性、子进程失败联动停止。
- 前端 Vitest：44 passed；OpenAPI types current；HTTP 模式 tsc/Vite build 通过；本次前端修改通过 Prettier。
- 后端 Ruff 检查/格式、API 契约和 git diff --check 通过。锁文件仅增加 SQLite extra，保留原 PyPI 来源；uv lock --check --offline 通过。
- 禁用 psycopg 导入的独立进程中，SQLite 初始化和会话创建成功；展示包不依赖 PostgreSQL 驱动。
- 真实浏览器连接本机生产构建前端及独立 worker，使用登记合成资料：同意处理说明 → 对话建档 → 确认档案 → JD 提取/确认 → 生成报告 → 深链接刷新；停止并重启整个展示栈后原浏览器会话读取到相同报告（66.7 为登记合成样例的覆盖分数，不是真实供应商结果）。
- 完整展示栈收到停止信号后正常退出。启动入口不保活，不请求平台放宽端口。

## 部署产物

- 文件：output/deployment/resumedoctor-show.zip（不提交 Git）。
- 白名单文件数：76；大小：257524 bytes。
- SHA-256：8bd1cc4baa91a8bd1dd04043c3b7e37ba9eb527cfeaaa27e3520edb2b0ce1ed9。
- 未包含 .env、Git、测试、上传原件、证据和数据库；源码扫描未发现凭证特征。
- 展示构建的资料保留文案说明休眠时清理暂停，不无条件承诺墙上时钟 24 小时内物理删除。

## 未执行及验收边界

- 本轮没有请求真实 DeepSeek/GLM，也没有消耗模型额度；配置目录检查不等于真实 AI 验收。
- 尚未部署到 mf18，不替换原静态页；Linux 展示容器的安装、内存/磁盘额度、平台休眠/唤醒、线上真实模型和班级登录后业务验收留给后续发布。
- Windows 未运行；进程监督的 POSIX 信号检查不表示 Windows 已通过。
- 本机浏览器仅完成上述一条合成流程；没有声称重新运行全部既有 Playwright 套件。多岗位、文件路径等由本轮后端集成测试覆盖，B 仍需按 docs/11-show-deployment.md 复验页面。
- SQLite 仅为单机低并发模式，不支持多副本/网络共享盘；不自动迁移已有 PostgreSQL 数据。未来 schema 变更须显式迁移。

## E 评审修正：Windows 符号链接权限（2026-11-03）

E 在 PR #66 的 Request changes 指出：Windows 缺少符号链接权限时，原静态隔离测试在
setup 阶段失败，其余断言没有执行。本次只调整测试，不修改应用、数据库或打包行为。

- 抽取普通前端构建 fixture；核心静态/SPA/API/私有文件隔离测试不创建符号链接，始终运行。
- 将符号链接逃逸拆成两项独立参数用例，分别检查 SPA 文件入口和 `/assets`；仅在创建链接
  抛 `OSError` / `NotImplementedError` 时跳过对应用例，提示 Windows 开发者模式/权限要求。
- 在核心用例加入编码 `..` 穿越探测，覆盖根入口与 assets，断言 404 且不泄露私有文本。
- `LLM_MODE=fake backend/.venv/bin/python -m pytest backend/tests/platform/test_show.py backend/tests/platform/test_sqlite.py -q`：**15 passed**，1 个既有依赖弃用 warning。
- 通过独立 Python 进程模拟 `Path.symlink_to` 抛权限错误和 `NotImplementedError`，分别执行
  `test_show.py -k static_`：每次 **1 passed、2 skipped**；另行断言结果计数，证明核心隔离仍执行，
  只有符号链接能力项跳过。该模拟不是 Windows 实机验收。
- Ruff 检查/格式及 `git diff --check` 通过。本次只改测试/记录，不重复初版全量、前端、浏览器、
  线上部署或真实模型验收；Windows 实机复验请 E 在本次提交后进行。
