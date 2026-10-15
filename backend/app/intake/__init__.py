"""M3 输入与结构化：语义校验与固定合成端口。

导入本包不访问数据库、不调用模型、不读取文件。
"""

from .errors import IntakeError
from .gateway_intake import DEFAULT_TIMEOUT_SECONDS, HISTORY_LIMIT, GatewayIntake
from .synthetic import (
    SYNTHETIC_JOB_RAW_TEXT,
    SYNTHETIC_SOURCE_ID,
    SYNTHETIC_SOURCE_TEXT,
    SYNTHETIC_SOURCES,
    SyntheticIntake,
    synthetic_job_content,
    synthetic_profile_content,
)
from .validation import (
    DEGREE_TARGETS,
    EDUCATION_VALUES,
    JobValidation,
    ProfileValidation,
    validate_job_content,
    validate_profile_content,
)

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "DEGREE_TARGETS",
    "EDUCATION_VALUES",
    "HISTORY_LIMIT",
    "SYNTHETIC_JOB_RAW_TEXT",
    "SYNTHETIC_SOURCES",
    "SYNTHETIC_SOURCE_ID",
    "SYNTHETIC_SOURCE_TEXT",
    "GatewayIntake",
    "IntakeError",
    "JobValidation",
    "ProfileValidation",
    "SyntheticIntake",
    "synthetic_job_content",
    "synthetic_profile_content",
    "validate_job_content",
    "validate_profile_content",
]
