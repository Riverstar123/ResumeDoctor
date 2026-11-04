# 展示站 SQLite 备选部署与验收

本模式用于小组在 `https://mf18.show.lingnan.top/` 低并发试用。平台说明：
<https://show.lingnan.top/docs>（核对于 2026-11-03）。平台不向 mf18 开放 PostgreSQL 端口，
因此使用本地 SQLite 文件，不使用网络隧道、端口转发或外部数据库代理。

## 架构与边界

- `app.database` 和独立 `app.platform.jobs` 按 `DATABASE_URL` 选择 PostgreSQL 或 SQLite，
  复用 `SQLRepository`、`JobStore` 和原有 M3/M4/M5。HTTP DTO、评分算法不变。
- PostgreSQL Alembic 迁移保留。SQLite 是独立新数据库，不导入或覆盖 PostgreSQL 资料；
  两种模式不能直接互换文件。
- SQLite 每个短事务执行 `BEGIN IMMEDIATE`，串行保护跨线程/进程的读取、判定和写入。
  仅忽略 `FOR UPDATE` 会破坏并发一致性，因此不能这样替换。启用 WAL、外键、UTC 时间、
  版本不可变触发器和有限锁等待；模型调用在事务外完成。
- 上传先单独提交原件清理预留，再在事务外写文件，最后在短事务中重新检查会话、幂等键并
  创建文档/任务。重复请求、部分写入或入库失败都会删除本次原件，删除失败保留持久清理项。
  写盘期间不持有 SQLite 写锁；连接池限制数据库连接数，HTTP I/O 限制整个操作的线程并发，
  两者不要求相等，超出连接数的操作等待连接归还。
- 任务保留原租约、续租、最多领取次数和总截止，不是内存队列。崩溃可在租约到期后接管，
  超过总截止的任务失败收敛，不承诺休眠后继续生成过期报告。
- `scripts/run_show.py` 显式初始化 SQLite，启动一个 API 和一个独立 worker；任一子进程
  退出时一起停止并返回失败，停止信号会传给两者。平台休眠时一起停止，访问时由平台唤醒。
  不额外发保活请求，不依赖常驻定时任务。
- 数据库、WAL/SHM 和上传原件在 `DATA_DIR`（平台为 `/data`），重新部署代码不覆盖数据。
  平台完全休眠时无法执行清理，到期原件在进程恢复后清理；这时不能保证墙上时钟 24 小时内
  已物理删除。试用优先用合成/脱敏资料。
- 仅适用于单机本地磁盘，不适用于网络共享盘、多副本或大量同时写入。资源超限仍需找老师，
  本模式不保证满足平台资源额度。

## 本地复现与打包

使用项目固定的 Python/Node 版本。SQLite extra 不需要 psycopg/PostgreSQL 服务：

```sh
uv sync --project backend --locked --extra sqlite
python3 scripts/package_show.py
```

打包脚本构建 HTTP 模式前端，写入仅使用 DeepSeek 的公开处理告知；只打包后端应用 Python
源文件、模型目录、前端构建产物、`requirements.txt`、`deploy.json` 和启动脚本。
不打包 `.env`、Git、依赖、测试、上传文件、文档、证据和数据库。
默认 ZIP 是 `output/deployment/resumedoctor-show.zip`；生成产物不代表部署完成。
构建前按平台用 `shutil.which` 查找 `npm.cmd`（Windows）或 `npm`（macOS/Linux），
使用找到的完整路径及参数列表启动；找不到时明确报错，不继续打包旧的构建产物。

文件解析保留 `python -I -X utf8`，通过解析模块旁的固定程序文件启动；该程序仅把自身位置
确定的后端根目录加入导入路径，不依赖工作目录、`PYTHONPATH` 或开发环境的 editable 安装。
路径不来自上传文件或请求参数，隔离解析、超时和子进程回收约束保持不变。

假模型本机验证（页面明确标记演示，不发外部模型请求）：

```sh
DATA_DIR=/tmp/rd-show-local \
SHOW_ORIGIN=http://127.0.0.1:8841 \
SESSION_COOKIE_SECURE=false LLM_MODE=fake PORT=8841 \
backend/.venv/bin/python scripts/run_show.py
```

Windows 在 PowerShell 分别设置环境变量，使用 `.venv/Scripts/python.exe`。
`/healthz` 仅证明 API 进程存活，必须提交并完成任务才能验证 worker。

只用 SQLite API/worker 时，先创建自己的数据目录，并配置
`DATABASE_URL=sqlite:////absolute/path/resumedoctor.sqlite3`：

```sh
uv run --project backend --extra sqlite python -m app.platform.repositories.sqlite
uv run --project backend --extra sqlite uvicorn app.database:create_app --factory
# 另一个终端，同一份配置
uv run --project backend --extra sqlite python -m app.platform.jobs
```

`PRAGMA user_version=1` 对应本次独立 schema；未知版本或已有未登记表拒绝初始化。
后续结构变更必须显式迁移，不能删除数据库或悄悄重建表。备份时停止 API/worker 后复制
整个数据目录，或使用 SQLite backup API，不能在写入期间只复制主 DB 而遗漏 WAL。

## 服务器配置（PR 验收后再发布）

Python 启动命令是 `python scripts/run_show.py`，读取平台 `PORT` 并监听 `0.0.0.0`。
前端和 `/api/v1` 同源，档案/报告深链接刷新可用；静态目录不公开数据库、原件或后端文件。
`PORT` 允许首尾空白，必须是有效 TCP 端口的十进制整数；带引号、非数字、空值或越界时，
启动器先打印明确的 `Invalid PORT environment variable` 并非零退出，不初始化数据或启动子进程。
`DATA_DIR` 通过 SQLAlchemy URL 构造并序列化，支持平台文件系统允许的百分号、空格、问号和
中文路径；不能手动拼接或预先转义这个环境变量。
展示入口关闭 `/docs`、`/redoc`、`/openapi.json` 及文档重定向，访问返回 404；普通开发入口
仍保留文档，业务 API 和离线接口契约检查不变。根目录 `output/` 已忽略，产物不提交 Git。

展示入口忽略本地 `.env`，默认 `LLM_MODE=real`，来源为小组 HTTPS 网址，Cookie 默认 Secure。
通过平台 `/api/secret` 设置以下服务端变量，禁止写进文件、`VITE_*`、PR、截图或部署包：

| 变量 | 内容 |
|---|---|
| `LLM_API_KEY` | 组长提供的 DeepSeek 密钥 |
| `LLM_BASE_URL` | 组长确认的 DeepSeek OpenAI-compatible API base URL |
| `LLM_MODEL` | 组长确认的实际 DeepSeek 模型名 |

模型名和端点不在代码预设，缺配置启动失败，不回退 fake。展示入口始终清空备用 DeepSeek
和 GLM 槽，只公开 `real-default`；通用目录仍保留 GLM 支持，其他开发环境不受影响。
API/worker 使用相同映射。按平台说明上传 ZIP、检查状态/部署日志、填写项目名和简介，
使用班级密码验收。资源超限应联系老师，不能绕过限制。

## 干净 ZIP 文件建档回归

打包和文件解析不能只在安装过项目本身的开发环境测试。先实际构建 ZIP，再解压到新目录，
给独立 Python 3.12 环境**只安装解压包的 requirements.txt**，不要运行 `pip install -e backend`。
下面为 macOS/Linux 示例，Windows 使用 `.venv/Scripts/python.exe` 并分别设置环境变量：

```sh
python3 scripts/package_show.py --output output/deployment/resumedoctor-show.zip
python3 -m zipfile -e output/deployment/resumedoctor-show.zip /tmp/rd-show-release
backend/.venv/bin/python -m venv /tmp/rd-show-runtime
/tmp/rd-show-runtime/bin/python -m pip install -r /tmp/rd-show-release/requirements.txt
RD_SHOW_ARCHIVE_ZIP="$PWD/output/deployment/resumedoctor-show.zip" \
RD_SHOW_ARCHIVE_PYTHON=/tmp/rd-show-runtime/bin/python LLM_MODE=fake \
backend/.venv/bin/python -m pytest backend/tests/platform/test_show_archive.py -q
```

该回归从实际 ZIP 再次解压，在独立解释器中先断言没有安装 `app`，再用解压源码的
`app.show` API 上传文件，由独立生产 worker 和隔离解析进程处理。合法 PDF/DOCX 必须成功
生成带来源位置的档案；损坏 PDF/DOCX 必须失败且不建档。全部使用登记合成资料和 fake 模型。
未提供两个 `RD_SHOW_ARCHIVE_*` 变量时，这四项明确跳过，不能记作干净包验收通过。

## 队友验收清单

1. **B / Web**：构建后页面走 `/api/v1`；同意处理说明、PDF/DOCX 上传、对话、编辑确认档案、
   提取确认 JD、多岗位报告、证据、导出、历史、深链接刷新、删除会话均可用，fake 标记清楚。
2. **C / 提取**：文件与对话保存正确来源引用，跨会话不可访问；补充经历产生新版本，旧版本不变。
3. **D / 评分**：同一确认快照重诊分数相同，不同 JD 独立评分，unknown 不变成 unmet。
4. **E / 模型与报告**：真实模式只列 DeepSeek；真实提取和报告实际拿到回答；失败降级保留评分，
   不静默切模型；缺密钥不能声称真实 AI 验收通过。
5. **A / 持久化**：幂等键只写一次，并发同版本编辑一次成功；两个进程只一个领取同一任务；
   崩溃接管拒绝旧租约；重启后原报告可读，过期任务明确失败；删除/清理有效；PostgreSQL 回归通过。

```sh
LLM_MODE=fake backend/.venv/bin/python -m pytest \
  backend/tests/platform/test_sqlite.py backend/tests/platform/test_show.py -q
make contracts
make lint
# 原 PostgreSQL 路径必须用已迁移的一次性测试库
RD_TEST_DATABASE_URL=<disposable-test-database> LLM_MODE=fake make test-security
```

本机合成模型验证、真实供应商、Windows、线上受限容器验收分别记录，不能互相替代。
当前 PR 仅提供发布准备代码与本机验证，不代表已上线。
本轮命令、结果与未测范围见 [本机验证记录](team/sqlite-deployment.md)。
