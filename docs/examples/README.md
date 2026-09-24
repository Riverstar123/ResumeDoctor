# 合成契约样例

全部内容虚构，仅用于 mock、算法手算和 Schema 校验，不是真实模型诊断结果。`model_metadata.provider=fake` 明确标记演示来源。

| 文件 | Schema | 用途 |
|---|---|---|
| [profile.json](profile.json) | Profile | Python 项目、SQL 自述、本科学历 |
| [job.json](job.json) | Job | 四条岗位要求 |
| [diagnosis-request.json](diagnosis-request.json) | DiagnosisCreate | 引用前两份已确认版本 |
| [diagnosis-item.json](diagnosis-item.json) | DiagnosisItem | 得分 66.7、SQL 部分满足、Docker 未知 |

示例 UUID 只用于文档，实际使用 API 时必须换成当前会话服务端返回的 ID。模型 `demo-model-a` 不是某个已接入的真实供应商名称。

## 按接口跑通一条对话路线（实现后）

1. POST `/api/v1/session`，body `{"consent_version":"v1"}`，浏览器保存 HttpOnly cookie。
2. GET `/api/v1/models`，选择支持 profile_chat/job_extract/diagnosis_report 的模型，记录其 id。
3. POST `/api/v1/profiles`，携带新 Idempotency-Key；content 为 `{"overview":"","as_of_month":"2026-09","facts":[],"evidence":[]}`（外层需再包 `content`），收到 Profile v1。
4. POST `/api/v1/profiles/{id}/messages`，body 包含 base_version=1、用户经历原文、model_id；携带新 Idempotency-Key，得到 task_id。
5. 轮询 GET `/api/v1/tasks/{task_id}`，succeeded 后按 result 获取 Profile 新版本；检查/编辑后 POST `/api/v1/profiles/{id}/confirm`，body 为最新 version。
6. POST `/api/v1/jobs`，body 包含 raw_text、company_context（可为空字符串）、model_id；携带新幂等键。轮询得到 Job，核对/编辑要求后确认。
7. POST `/api/v1/diagnoses`，body 参照 diagnosis-request.json，全部 ID 替换为实际已确认资源，model_id 为报告模型；携带新幂等键。
8. 用返回的 task_id 轮询；用 diagnosis_id 读取逐岗位结果。终态可 GET `/api/v1/diagnoses/{id}/export` 下载 Markdown。

上传路线只需把第 3–5 步替换为 POST `/api/v1/documents`（multipart file + model_id），轮询取得草稿，再检查并确认。比较多个 JD 时重复步骤 6，诊断 body.jobs 填 1–5 项。
切换报告模型：保留相同 profile/jobs 版本引用，仅换 model_id 与新 Idempotency-Key；预期评分完全相同，建议文字可不同。
