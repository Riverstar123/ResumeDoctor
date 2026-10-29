"""QA-03 Playwright 专用后端启动器：按变体名设置 RD_E2E_* 后启动 uvicorn。

只从命令行/服务端环境读取配置（见同目录 fixture_app.py 的安全约束），
浏览器请求无法影响任何故障开关。文件无 test_ 前缀，不会被 pytest 收集。

用法（工作目录为 backend/）：
    .venv/Scripts/python -m tests.e2e.serve \
        --variant partial --port 8011 --origin http://127.0.0.1:5181

变体：
- success：全部成功的确定性 fake 链路
- partial：每个双岗位诊断的第二份报告 invalid_json（重试 1 次后仅评分）
- fail：诊断任务在开始前即失败（供应商不可用注入），用于「全部失败/不可导出」
- slow：仅拖慢诊断任务整体开始，用于「任务运行中删除会话」

已有环境变量优先（setdefault），便于本地临时调整延迟；不要用它从请求侧传参。
"""

import argparse
import json
import os

import uvicorn

VARIANTS = {
    "success": {
        "RD_E2E_EXECUTOR_DELAY": "0.01",
    },
    "partial": {
        "RD_E2E_EXECUTOR_DELAY": "0.01",
        "RD_E2E_REPORT_FAIL_INDEX": "1",
        "RD_E2E_REPORT_FAIL_EVERY": "2",
        "RD_E2E_REPORT_FAIL_BEHAVIOR": "invalid_json",
    },
    "fail": {
        "RD_E2E_EXECUTOR_DELAY": "0.01",
        "RD_E2E_TASK_FAILURES": json.dumps({"diagnosis": "PROVIDER_UNAVAILABLE"}),
    },
    "slow": {
        # 只拖慢 diagnosis 总入口，提取类任务不受影响；配合运行中删除会话用例。
        "RD_E2E_EXECUTOR_DELAY": "12",
        "RD_E2E_DELAY_OPS": json.dumps(["diagnosis"]),
    },
}


def main() -> None:
    parser = argparse.ArgumentParser(description="QA-03 fake-stack E2E backend launcher")
    parser.add_argument("--variant", required=True, choices=sorted(VARIANTS))
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--origin", required=True, help="配套 Vite 源，用于 ALLOWED_ORIGINS")
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    for key, value in VARIANTS[args.variant].items():
        os.environ.setdefault(key, value)
    os.environ["ALLOWED_ORIGINS"] = json.dumps([args.origin])

    uvicorn.run(
        "tests.e2e.fixture_app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    main()
