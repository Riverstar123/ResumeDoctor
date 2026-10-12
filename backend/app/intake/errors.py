"""M3 内部错误；HTTP 状态码映射由 M2 负责，本模块不产生响应。"""


class IntakeError(ValueError):
    """校验或提取失败。

    code 是给调用方（M2）看的机器可读标识；message 是给人看的中文说明。
    与 M4 的 ScoringError 保持同样的形状，便于平台层统一映射。
    """

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)
