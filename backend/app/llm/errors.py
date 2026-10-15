"""M5 模型网关内部错误；HTTP 状态码映射由 M2 负责，本模块不产生响应。

与 M3 的 IntakeError、M4 的 ScoringError 保持同样的形状（code + message），
便于平台层统一映射。code 只取 [06-ai-contract](../../../docs/06-ai-contract.md)
规定的可区分失败：MODEL_UNAVAILABLE、PROVIDER_UNAVAILABLE、MODEL_TIMEOUT、
MODEL_OUTPUT_INVALID、INPUT_TOO_LONG。
"""


class GatewayError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)
