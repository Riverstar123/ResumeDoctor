"""Audit C/E output files without a provider, database or private credentials."""

import argparse
import json
from pathlib import Path

from report_contract import check_report_contract

from app.contracts import DiagnosisItem, Job, Profile
from app.tools.check_contracts import example_validator, load_design


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--item", required=True)
    args = parser.parse_args()
    design = load_design()
    values = {}
    for name, path in (("Profile", args.profile), ("Job", args.job), ("DiagnosisItem", args.item)):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        example_validator(design, name).validate(data)
        values[name] = data
    profile = Profile.model_validate(values["Profile"])
    job = Job.model_validate(values["Job"])
    item = DiagnosisItem.model_validate(values["DiagnosisItem"])
    if not profile.confirmed or not job.confirmed:
        raise ValueError("snapshots must be confirmed")
    if (item.job.id, item.job.version) != (job.id, job.version):
        raise ValueError("DiagnosisItem references another Job version")
    check_report_contract(profile.content, job.content, item)
    print("OpenAPI and deterministic score/report reference checks passed.")


if __name__ == "__main__":
    main()
