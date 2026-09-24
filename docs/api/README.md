# HTTP API v0.1

机器可读契约：[openapi.json](openapi.json)。Base path `/api/v1`。这是未来接口设计，当前没有运行服务。所有业务 JSON 字段采用 snake_case，资源 ID 为 UUID，UTC 时间字符串。示例：[单岗位诊断结果](../examples/diagnosis-item.json)。

## 会话与模型选择

POST /session 创建匿名会话，body consent_version=`v1`；响应设置 `rd_session` HttpOnly、SameSite=Lax cookie，生产 Secure=true。模型处理说明必须先由用户接受。有效期 7 天固定，现有有效 cookie 重复创建返回同一会话，不静默清空。
除 POST /session 外均需要有效 cookie。写请求核对允许的 Origin（非浏览器客户端也需要可信来源策略）；cookie 不暴露给 JS。GET /models 返回可用 id、display_name、provider、capabilities 与默认值；前端按能力筛选下拉菜单，用户不输入密钥或任意供应商 URL。
上传、对话、JD 提取、诊断创建都显式传 model_id；诊断模型只负责报告。用户切换仅影响之后提交的任务，已有任务保持原模型。模型失效返回 MODEL_UNAVAILABLE，不自动换更贵模型。

## 资源与版本

Profile/Job 外层含 id、version、confirmed、content。GET 无 version 取最新，?version=n 取指定版本。PUT 携带 base_version+content（Job 还含 raw_text），完整替换创建新草稿版本；确认 POST /.../confirm body={version}，仅允许 latest，旧已确认版本可继续被诊断引用。
新档案可以 POST /profiles 手动建空草稿（content 的 facts/evidence 可为空）；之后对话或编辑完善。上传成功由任务结果返回新 profile_id 和 version。
GET /profiles/{id}/messages 返回本会话该档案成功轮次的完整消息列表，MVP 上限 50 轮，不分页。失败轮次在前端允许重试，不伪装成已保存成功。

## 路由概览

| 方法与路径 | 返回 | 负责人 |
|---|---|---|
| POST /session；DELETE /session | 200 session；204 删除 | M2 |
| GET /models | 200 ModelList | M2 路由 / M5 配置 |
| POST /profiles；GET/PUT /profiles/{id} | 201 / 200 Profile | M2 / M3 校验 |
| POST /profiles/{id}/confirm | 200 Profile | M2 |
| POST /documents（multipart file+model_id） | 202 TaskAccepted | M2 / M3 |
| POST /profiles/{id}/messages | 202 TaskAccepted | M2 / M3 |
| GET /profiles/{id}/messages | 200 MessageList | M2 |
| POST /jobs | 202 TaskAccepted | M2 / M3 |
| GET/PUT /jobs/{id}；POST /jobs/{id}/confirm | 200 Job | M2 / M3 |
| POST /diagnoses | 202 DiagnosisAccepted | M2 / M4 / M5 |
| GET /tasks/{id} | 200 Task | M2 |
| GET /diagnoses/{id} | 200 Diagnosis | M2 |
| GET /diagnoses/{id}/export | 200 text/markdown | M2 / M5 |

导出正在执行的诊断返回 409；partial 可导出已完成评分并标注报告失败，failed 全无分数返回 409。

## 异步结果

202 返回 task_id；诊断额外返回 diagnosis_id。前端约每 2 秒轮询 GET /tasks/{id}，终态停止，页面离开停止计时；429 尊重 Retry-After。task.result 成功后含 resource_type=profile/job/diagnosis、resource_id、version（诊断为 null）；对话结果另有 assistant_message。
task.kind=document_parse/profile_chat/job_parse/diagnosis。错误以 error.code/message 表示；failed 的 result 可为空；partial 只对诊断，result 指向包含逐项错误的诊断资源。
不能把返回 202 当作诊断成功；GET /diagnoses 在处理中也返回当前 items。

## 幂等与并发

所有 POST 除 /session 和 /confirm 外必须带 Idempotency-Key（16–128 字符随机键）。同一会话相同 key 和相同 operation/body 返回同一个资源与首次状态码；内容不同返回 409 IDEMPOTENCY_CONFLICT。multipart 哈希含文件字节与 model_id。key 保留 24 小时，前端网络重试沿用原 key，用户主动重新诊断使用新 key。
同档案只能有一个运行中的提取/对话任务，409 PROFILE_BUSY；编辑若在后台提交前发生，后台以 VERSION_CONFLICT 失败。每会话最多 2 个并发任务；超出 429。
PUT 的 base_version 防止覆盖，不需要 Idempotency-Key；重复过期 PUT 返回 409，客户端重新 GET 核对。

## 错误统一格式

`{"error":{"code":"VERSION_CONFLICT","message":"资料已更新，请刷新后重试","details":{}},"request_id":"..."}`

| HTTP | 错误码示例 | 处理 |
|---|---|---|
| 401 | SESSION_EXPIRED | 提醒会话过期，重新进入；不静默假装资料仍在 |
| 403 | ORIGIN_FORBIDDEN | 固定部署/开发来源配置 |
| 404 | RESOURCE_NOT_FOUND | 不区分不存在与其他用户资源 |
| 409 | VERSION_CONFLICT / PROFILE_BUSY / IDEMPOTENCY_CONFLICT / NOT_READY | 刷新或等待，不盲目覆盖 |
| 413 | FILE_TOO_LARGE | 更换文件 |
| 415 | UNSUPPORTED_FILE_TYPE | 仅文字 PDF/DOCX |
| 422 | VALIDATION_ERROR / UNCONFIRMED_VERSION / NO_SCORABLE_REQUIREMENTS / MODEL_UNAVAILABLE | 定位字段修正 |
| 429 | RATE_LIMITED | 返回 Retry-After 秒数 |
| 500 | INTERNAL_ERROR | 返回 request_id；不暴露堆栈 |

后台错误另含 NO_TEXT_LAYER、DOCUMENT_PARSE_FAILED、MODEL_TIMEOUT、MODEL_OUTPUT_INVALID、PROVIDER_UNAVAILABLE、INPUT_TOO_LONG、TASK_TIMEOUT。后台错误记录于 Task/DiagnosisItem，不通过轮询接口的 HTTP 500 重复表达。

## 契约更改

OpenAPI 为 HTTP 结构唯一来源。先改 schema/示例/影响说明，相关消费者评审，再实现。新增可选字段可兼容；删除字段、改枚举语义、改 required 必须显式版本记录。FastAPI 生成契约需在 CI 与此设计比对，不允许实现后反向悄悄覆盖设计。

## Schema 之外的业务校验

JSON Schema 检查形状，服务端还必须检查：facts/evidence/requirements 的局部 ID 唯一；引用存在且属于当前快照；quote 属于真实来源；month 区间合法且 as_of_month 不晚于当前月；min_months 的 target 是正整数且 subject 非空；degree_at_least target 是允许学历；ignored=true 有明确原因；相同 JD 不得以不同版本在同一次诊断重复提交。
ScoreResult 必须由 M4 生成，status/coefficient/weight 一致（met=1、partial=0.5、其余=0，must=2、preferred=1）；分母与分类分数可重算；ignored 要求不产生 assessment。报告引用只能来自冻结快照，gaps 与 assessment 状态对应。
DiagnosisItem 的状态不变量：succeeded 同时有 score_result/report/model_metadata 且 error=null；score_only 有 score_result、report=null 与具体 error；failed 无评分且有 error；pending/scoring/reporting 只允许已完成阶段的数据。Task succeeded/partial 必须有 result；failed 必须有 error。

完整调用顺序见 [合成样例与接口演练](../examples/README.md)。
