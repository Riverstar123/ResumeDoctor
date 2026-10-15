# IN-02 / PR #48 评审修复

关联 [PR #48](https://github.com/Riverstar123/ResumeDoctor/pull/48)、[Issue #16](https://github.com/Riverstar123/ResumeDoctor/issues/16)。本轮原始审查提交为 `096bfd909b022786a53462e9b83b6662b59d479b`，base=main。修复期间 C 又提交 `a4dd01c`、`15aead9`；已检查并保留其双 JD fixture、统一月份来源、首尾空白匹配及版本守卫，合并时将 Callable 隐私策略导入与 C 的 date 来源修正一起保留，未整块选择某一侧。C 的固定合成端口 PR #44、E 的假网关 PR #46 均已合并并通过评审；main 中的实际 merge commit 分别为 `b024b993dd42373043f876879987ed4acb1cb563`、`ce142a13572ceb2d20848731d058f72cb26e95ad`。本轮使用合成资料，不调用真实供应商。

用户已明确授权评审并直接修复代码，沿用 PR #48 的现有分支；不把本次修复写入 INT-01 分支，不另开开发 PR。未合并、不关闭 Issue；修复提交还需要队友复审。

## 发现与处理

| 问题 | 原始实现与独立反例 | 修复 / 证据 |
|---|---|---|
| 旧证据无法跨轮保留 | `advance_conversation` 仅以最近用户消息和本轮原文校验整份新档案。模型原样返回已有档案，来源不在窗口或来自之前的文档时会 UNKNOWN_SOURCE；原测试还允许模型丢弃既有事实 | `validate_profile_content` 新增内部可选 `previously_verified_evidence`，只接受调用方先前已验证快照的**完全相同**证据；GatewayIntake 拒绝遗漏事实、遗漏/改写既有证据。新增证据仍须核对来源及原文，不能复用旧 source_id 绕过校验 |
| 历史来源编号未传给网关 | 原来只发送字符串文本列表，却按 `Message.id` 校验历史引用。已有单测预先把正确 ID 写进假响应，不能证明模型收到足够的来源信息 | `history_user_messages` 改为 `{source_id, content}` 记录列表；只取最近 10 条 role=user 消息。每段正文仅发送一份，避免双份文本消耗 30,000 字符网关预算 |
| 联系方式原样进入模型上下文 | 合成邮箱/电话在本轮、历史或既有档案中均可原样进入网关；依据 `docs/06-ai-contract.md`，外部模型调用前必须移除联系方式 | fake 默认递归复制并过滤常见联系方式。无显式隐私策略的非 fake 网关在调用前拒绝；显式策略由调用方配置，不声称这些局部正则已经完成真实供应商的隐私验收 |

旧证据隐私处理：若模型原样返回发送给它的、已过滤联系方式的旧证据投影，M3 仅根据完全匹配的证据 ID 和内容恢复调用方已保存的原证据，不把删除联系方式后的改写当成新原文。模型若改动其他字段则拒绝，不为新证据拼接或猜测原文。输入快照保持不变。

## 消费者影响

- HTTP OpenAPI、共享 DTO、IntakePort、TaskContext、数据库和依赖锁文件不变；不修改 M1/M2/M4/M5 实现。
- M5 后续真实适配器需保留每条历史记录的 source_id/content 对应关系。提示词文本和版本保持原样；增加来源字段只改变本 PR 尚未交付的内部数据组织方式，不新造输出 DTO。
- `previously_verified_evidence` 只能由调用方从已验证、已保存的上一快照传入，禁止传入本轮模型生成的数据。默认值为空，原有校验调用不放宽；唯一 ID、引用、日期和学历等检查仍执行。
- `GatewayIntake(..., privacy_filter=...)` 为可选内部配置；策略同步处理整个上下文，保留 DTO 结构，且每次请求仅执行一次。没有策略且网关没有明确 `is_fake=True` 时抛 `IntakeError(code="PRIVACY_FILTER_REQUIRED")`，模型调用不会发生。M2 接真实网关前还需明确该配置错误的安全映射；本 PR 不新增 HTTP 错误码契约。
- 默认 fake 规则覆盖常见邮箱、手机号、国际号码及带标签的电话/地址示例，不能可靠识别所有自然语言中的详细地址，也不应作为真实隐私策略。真实策略需由 C/E/A 按提供商与数据处理告知共同核对后注入；本轮没有真实发送证据。
- 来源编号接口缺口继续明确：构造参数 source_id 只能作为**请求级**来源绑定，不能让一个全局实例用固定编号代表所有实际消息/文档。M2 尚未在调用前预留消息编号；本轮不默默扩签共享协议或声称 HTTP 来源持久化已完成。A/C 后续应协调 TaskContext 的可选来源标识与提交消息 ID 一致，再修改平台装配并联测。
- E 的 FakeModelGateway 仍以固定合成素材输出；从空档案提取任意对话、两个不同 JD 的全链路不是本次边界修复的交付。C 同轮已补 SyntheticIntake 的两个 JD fixture，本轮保留并复验；HTTP 装配与 #13 验收仍需合入 main 后协调，不在 GatewayIntake 内覆盖模型输出字段来伪造成功。另修正 synthetic.py 文档：档案方法实际仍以固定来源表校验，不能声称任意未知档案原文会被拒绝。

## 实际验证

环境：macOS / Python 3.12.13 / uv 0.11.15。执行使用本任务独立新 venv、项目锁定依赖与已准备缓存（`UV_NO_CONFIG=true`、`UV_OFFLINE=true`、独立 `UV_PROJECT_ENVIRONMENT`）；没有覆盖原有私人配置或损坏的旧 Python 环境。命令来自 Makefile。

1. 原始 PR 的独立干净源码快照：`PYTHONUTF8=0 make setup test contracts lint`，277 passed；36 Schema / 4 示例 / 18 业务操作，pending=[]；Ruff check / format 通过。
2. 在上述未修复快照补充三个独立反例（原样旧档案保留、历史来源 ID 可见、电话邮箱不进入网关）：3 failed，分别为 UNKNOWN_SOURCE、缺少 ID、联系方式仍存在。只使用合成输入。
3. 合并 C 并发更新前的完整 `PYTHONUTF8=0 make test contracts lint`：294 passed；36 Schema / 4 示例 / 18 业务操作，pending=[]；Ruff check / format（63 个文件）通过。合并后完整同命令再次通过：299 passed；36 Schema / 4 示例 / 18 业务操作，pending=[]；Ruff check / format（63 个文件）通过。C 新增的 5 项 fixture 用例保持通过。
4. 新增 `backend/tests/intake/test_gateway_intake_boundaries.py`：17 passed。覆盖两轮来源独立绑定、窗口外证据保留、旧 ID 篡改/遗漏拒绝、新证据无法借旧来源、历史不采纳 assistant、来源类型一致、过滤后旧证据还原、未配置非 fake 网关调用前拒绝、显式策略只执行一次、联系方式嵌套过滤且不更改日期/输入、较长历史不因重复正文超预算。

未执行：真实供应商、真实 Windows 复测、页面/HTTP 的 GatewayIntake 装配、真实来源编号事务和 B 的 #13 复现。保留这些边界，不把纯模块测试通过当作五模块验收或全项目验收。
