"""M5 报告模块内部错误；HTTP 状态码映射由 M2 负责，本模块不产生响应。

与 M3 的 IntakeError、M4 的 ScoringError 保持同样的形状（code + message），
便于平台层统一映射。报告内容不合法统一使用 MODEL_OUTPUT_INVALID，使 M2 可以把
该岗位降级为 score_only，同时保留已经算好的规则评分。
"""


class ReportError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)
