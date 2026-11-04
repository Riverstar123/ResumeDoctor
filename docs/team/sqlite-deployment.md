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

## B/C/D 评审修正：Windows npm 启动（2026-11-04）

B、C、D 在 `c33e3bf` 均指出：正常安装的 Windows Node 提供 `npm.cmd`，打包器通过
裸名称 `npm` 启动会在构建前报 WinError 2。本次用 `shutil.which` 按平台解析
`npm.cmd` / `npm` 的实际路径，再通过参数列表调用；找不到时在构建/ZIP 写入前明确报错。

- SQLite/展示入口相关测试：**20 passed**，1 个既有依赖弃用 warning。新增五个参数用例，
  覆盖 Windows/macOS/Linux 的路径选择及含空格路径保持单参数、HTTP 模式构建后 ZIP 生成，
  以及 Windows/Linux 缺少命令时不调用 subprocess、不写 ZIP。平台选择和 subprocess 为受控替身，
  不作为 Windows 原生进程启动已通过的证据。
- 在 macOS 实际使用 Node **24.14.1** 执行
  `python3 scripts/package_show.py --output output/deployment/resumedoctor-show-pr66-npm.zip`，
  tsc/Vite HTTP 构建及打包通过；ZIP 白名单 **76** 文件、**257524 bytes**，内容检查通过。
- 本次 ZIP SHA-256：`2ecc77fc5bbfb82c376d62b5496db84b634e0fda9b5945ec2ca0e1c981a9f7c1`。
  ZIP 留在本地 output，不提交或上传；上方“部署产物”为初版记录。
- Ruff 检查/格式与 `git diff --check` 通过。应用/数据库代码、接口和密钥配置未变，
  不重复初版 PostgreSQL 全量和网页流程；未发真实模型请求、未上线。请 B/C/D 在现有 Windows
  安装环境执行完整打包入口后复审，不要求因本问题重装 Node 或改动系统 PATH。


## C 评审修正：干净 ZIP 的隔离解析导入（2026-11-04）

C 在 `57d8efd` 发现部署 ZIP 中合法 PDF/DOCX 都建档失败：主进程的 PYTHONPATH 在
解析子进程的 `-I` 模式下被忽略，ZIP 又没有安装项目本身。本轮已用真实旧 ZIP 复现：
干净环境的四项回归为 **2 failed / 2 passed**，两个合法文件均报 DOCUMENT_PARSE_FAILED。

修复为按 `documents.py` 自身位置找到固定的 `document_worker.py`，继续使用 `-I -X utf8`
直接执行；worker 仅从其自身程序位置加入固定后端目录。没有移除隔离、不读取上传文件路径
来选择代码，也不要求在服务器安装 editable 项目或额外写入 site-packages。

- 新增受信任路径检查：保留实际 -I/UTF-8 子进程，在伪造同名 app 的工作目录和 PYTHONPATH
  下仍提取正确文字。原有损坏/加密/无文字/超限、超时和取消回收用例仍执行。
- 解析、SQLite、展示入口相关测试：**65 passed**，1 个既有依赖弃用 warning。
- 创建全新 Python **3.12.13** venv，仅安装实际 ZIP 内 requirements.txt 的运行依赖；
  初次安装引用与 ZIP 字节一致的依赖文件，并按 uv.lock 约束传递依赖，随后直接对解压包的
  requirements.txt 执行确认安装。未安装项目本身、pytest、数据库驱动或开发依赖。
- 使用 Node **24.14.1** 实际构建修复 ZIP 后，通过 RD_SHOW_ARCHIVE_ZIP 和
  RD_SHOW_ARCHIVE_PYTHON 运行新 `test_show_archive.py`：**4 passed**。每项均用干净解释器
  的 app.show API、独立生产 worker 和隔离解析子进程；合法 PDF/DOCX 各生成含三条登记事实、
  来源与位置的档案，损坏 PDF/DOCX 明确失败且档案计数为零。
- helper 首先确认隔离解释器无法发现已安装的 app，防止 editable 安装掩盖导入问题；测试支持
  解压路径含空格。未配置干净解释器/实际 ZIP 时四项会显式跳过，不等于通过。
- 新 ZIP：`output/deployment/resumedoctor-show-pr66-parser.zip`；**76 文件 / 257732 bytes**；
  SHA-256：`6801d3f25b907a7778df51dcf006e6b902a474d9100544efdc52172ebd45e26b`。CRC、重复条目和白名单检查通过；只保留在本地，未上传。
- Ruff 检查/格式、接口契约和 diff 检查通过。未重跑 PostgreSQL 全量、Windows 实机或完整浏览器；
  本轮均为 fake，不调用真实模型，未执行展示平台部署或休眠唤醒验收。请 C 对干净 Windows ZIP
  路径复验，其他评审人的已通过范围不自动等于本次提交已通过。
