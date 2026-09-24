# 五人 GitHub 协作：从第一次使用开始

## 名词对照

仓库是项目和历史；clone 是下载一份可同步副本；branch 是自己的工作线；commit 是本地保存的变更记录；push 是上传；PR 是请队友审核并合并；Issue 是明确任务；pull 是更新本地。
五人各自 clone 同一个仓库，不共享同一个本地文件夹。新手可以用 GitHub Desktop 完成克隆、分支、提交、推送，再在网页开 PR。

## A 首次设置远程（由用户执行）

本地已经按请求初始化并提交文档后：在 GitHub 创建仓库，建议初始不勾选 README/.gitignore/license，避免和本地首个提交产生两套历史。替换下面占位符：

```bash
git remote add origin https://github.com/<OWNER>/<REPO>.git
git push -u origin main
```

若远程已经有内容，先 fetch 检查历史再整合，不用 force 覆盖。不要把密码/API key 写进 remote URL。认证使用 GitHub 支持的账户登录或 SSH/凭证管理。
邀请另外四人协作；将 A–E 替换为真实人名/用户名；确认仓库可见性与课程要求。
在仓库设置中按可用权限配置 main 的 PR 审核规则（至少 1 位队友审核）、禁止强推；分支保护是否可用取决于账户/仓库配置，未配置不能假称启用。

## 每个人第一次

1. 接受仓库邀请，安装 Git 或 GitHub Desktop，完成账户认证。
2. clone 远程；在该目录启动 Claude Code，阅读根 README 和 CLAUDE.md。
3. 配置自己的 git user.name/user.email（邮箱可使用 GitHub 隐私邮箱），不要使用组长身份。
4. 先认领一个文档小任务，跑通 PR；有问题让 Claude 解释当前状态，不直接执行网上“重置全部”指令。

## 日常流程（实现阶段同样适用）

```bash
git switch main
git pull --ff-only
git switch -c docs/12-review-m3
# 编辑本任务相关文件；开发任务可命名 feat/23-profile-editor
git status
git diff
git add docs/modules/M3-intake.md
git commit -m "docs: clarify intake contract"
git push -u origin docs/12-review-m3
```

在 GitHub 点击 Compare & pull request，填模板，关联 `Closes #12`（替换成真实 Issue 编号），请求指定队友评审。通过后 A 或被授权的维护者合并；默认 squash merge，一个任务一个清楚的主线记录。
然后切回 main 并 pull，再开下一个分支。还没提交的修改先妥善保存，别直接切分支或用 reset --hard。

## 分支落后与冲突

在自己功能分支上，先保证改动已提交，再 `git fetch origin`、`git merge origin/main`。遇冲突先看双方意图，和相关 owner 对齐；用 Claude 解释每一处再修改，禁止全部选 ours/theirs。验证后提交 merge；没把握先保留现场求助 A。
不需要新手学习 rebase/force push 才能参与。不要向 main 直接提交业务开发，不把每个人长期放在永不合并的个人分支。

## Issue 看板

列：Todo → In progress → In review → Done；标签：M1/M2/M3/M4/M5、docs、feature、bug、blocked、contract。一个 Issue 一个主要负责人、一组验收标准。相关依赖用 Issue 链接写清。
任务池在 [backlog.md](backlog.md)，需要团队建立远程后手动创建，不表示 GitHub 上已有这些 Issue。

## 代码以外也必须检查

不要提交 `.env`、真实简历/对话、模型 key、数据库、截图中的个人信息；只 add 本任务文件。`.gitignore` 不能移除已经追踪的敏感文件；若误提交秘密立即撤销凭证并联系 A，单纯删除下一版文件不够。
本地第三方 `.claude/skills` 被忽略，项目 CLAUDE.md 与文档会共享。

参考：[GitHub Flow 官方说明](https://docs.github.com/en/get-started/using-github/github-flow)。
