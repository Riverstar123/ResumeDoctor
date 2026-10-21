"""M5 报告：结构化报告生成、语义校验与 Markdown 导出。

导入本包不读取 settings、不连接数据库或供应商；fake 模式不需要 API key。
"""

from .errors import ReportError
from .markdown import export_markdown
from .prompts import REPORT_PROMPT, REPORT_PROMPT_VERSION
from .service import DEFAULT_TIMEOUT_SECONDS, ReportService
from .validation import GAP_KIND_BY_STATUS, validate_report

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "GAP_KIND_BY_STATUS",
    "REPORT_PROMPT",
    "REPORT_PROMPT_VERSION",
    "ReportError",
    "ReportService",
    "export_markdown",
    "validate_report",
]
