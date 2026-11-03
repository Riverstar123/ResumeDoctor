"""Build the HTTP frontend and package only approved deployment inputs."""

import argparse
import os
import re
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTICE = (
    "本应用使用 DeepSeek 处理简历、对话和岗位要求，用于提取事实及生成诊断建议。"
    "所选模型会接收处理所需的内容；电话和邮箱会过滤，但学校、公司及其他经历信息"
    "仍可能传输到外部供应商。请确认后使用。"
)
RETENTION_NOTICE = (
    "原始文件解析结束后清理；服务运行期间最迟 24 小时清理。展示服务休眠时暂停处理和清理，"
    "恢复后清理到期资料，因此原件的实际保留时间可能超过 24 小时。"
    "结构化资料随会话过期或删除清理。请先使用合成或脱敏资料试用。"
)


def package(output, *, build=True):
    if build:
        env = dict(os.environ)
        env.update(
            VITE_API_MODE="http",
            VITE_API_BASE_URL="/api/v1",
            VITE_PROCESSING_NOTICE=NOTICE,
            VITE_RETENTION_NOTICE=RETENTION_NOTICE,
        )
        subprocess.run(
            ["npm", "run", "build"], cwd=ROOT / "frontend", env=env, check=True
        )
    files = [
        ROOT / name
        for name in ("deploy.json", "requirements.txt", "scripts/run_show.py")
    ]
    files += sorted((ROOT / "backend/app").rglob("*.py"))
    files += [ROOT / "backend/config/models.yaml"]
    files += sorted(
        path for path in (ROOT / "frontend/dist").rglob("*") if path.is_file()
    )
    if not (ROOT / "frontend/dist/index.html").is_file():
        raise ValueError("The built frontend is missing")
    files = [
        path
        for path in files
        if not any(part.startswith(".") for part in path.relative_to(ROOT).parts)
    ]
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError("Deployment inputs must be regular project files")
        if re.search(rb"sk-[A-Za-z0-9_-]{16,}", path.read_bytes()):
            raise ValueError(
                f"Possible API credential in deployment input: {path.relative_to(ROOT)}"
            )
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
    print(f"Packaged {len(files)} files: {output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "output/deployment/resumedoctor-show.zip"
    )
    args = parser.parse_args()
    package(args.output)


if __name__ == "__main__":
    main()
