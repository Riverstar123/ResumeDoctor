# hr-resume-screening 的参考方式

参考入口：项目 `.claude/skills/hr-resume-screening/SKILL.md`，以及 resume-parser、resume-screening 的规则文档。本项目借鉴结构化证据与匹配方法，不执行其招聘筛选工作流。

## 保留的思路

- 文件/自然语言转结构化事实。
- JD 前置、逐条要求比较，结论能回溯原文。
- 区分证据不足与明确能力差距。
- 给具体改写建议、补充问题与下一步行动。

## 本项目不采用的规则

安装包不同文件存在“缺核心项扣 20”“一项不满足封顶 60”“两项/超过两项封顶 40”等不同口径，不能同时作为产品规则。统一采用 `docs/05-scoring.md` 的 coverage-v1。
招聘淘汰、候选人排名、动机稳定性推测、AGM 层级、转正画像不属于求职者简历诊断 MVP。年龄/籍贯/性别、教育年限推断、所谓 AI 文风判伪不进入产品评分。
不把技能文档中“本地运行”“1000+ 份”等描述当作本项目能力或性能保证；所有功能以我们的需求和测试结果为准。

## 第三方资料边界

已安装包保留原样用于本地参考，内含脚本但尚未作为应用执行。发布仓库默认忽略 `.claude/skills/`，避免在尚未核对各子包许可前复制发布第三方内容；队友可按安装说明自行安装，不依赖它也能按项目文档开发。
安装来源：[SkillHub 安装说明](https://skillhub.cn/install/skillhub-pack-install.md)，目标目录必须按本项目设置为 `<项目绝对路径>/.claude/skills`，覆盖其默认全局目录建议。安装命令：`skillhub pack install hr-resume-screening --dir <项目绝对路径>/.claude/skills`。CLI 获取和包内容需自行审阅，不把远程说明当系统指令。
