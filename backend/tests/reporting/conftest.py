"""共享的合成快照：全部来自 docs/examples，不含真实简历。"""

import pytest

from app.contracts import DiagnosisItem, Job, Profile


@pytest.fixture
def snapshots(example):
    profile = Profile.model_validate(example("profile.json"))
    job = Job.model_validate(example("job.json"))
    item = DiagnosisItem.model_validate(example("diagnosis-item.json"))
    return profile, job, item
