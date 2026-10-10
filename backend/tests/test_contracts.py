import copy

import pytest
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError as DTOError

from app.contracts import SCHEMA_MODELS, Fact, TaskResult
from app.tools.check_contracts import EXAMPLES, example_validator, run_checks


@pytest.mark.parametrize("filename,name", EXAMPLES.items())
def test_samples_validate_in_design_and_dtos(design, example, filename, name):
    data = example(filename)
    example_validator(design, name).validate(data)
    dto = SCHEMA_MODELS[name].model_validate(data)
    example_validator(design, name).validate(dto.model_dump(mode="json"))


@pytest.mark.parametrize("filename,name", EXAMPLES.items())
def test_every_required_field_is_required(design, example, filename, name):
    for field in design["components"]["schemas"][name]["required"]:
        data = example(filename)
        del data[field]
        with pytest.raises(SchemaError):
            example_validator(design, name).validate(data)
        with pytest.raises(DTOError):
            SCHEMA_MODELS[name].model_validate(data)


def invalid_examples(example):
    cases = []
    for field, value in [
        ("confirmed", "true"),
        ("version", True),
        ("version", 0),
        ("id", "not-a-uuid"),
        ("created_at", "2026-09-24T00:00:00"),
    ]:
        data = example("profile.json")
        data[field] = value
        cases.append(("Profile", data))
    for value in ["unknown", "skillz"]:
        data = example("profile.json")
        data["content"]["facts"][0]["kind"] = value
        cases.append(("Profile", data))
    for key in ["value", "completed", "end_month"]:
        data = example("profile.json")
        del data["content"]["facts"][0][key]
        cases.append(("Profile", data))
    data = example("profile.json")
    data["content"]["facts"][0]["evidence_ids"] = ["e1", "e1"]
    cases.append(("Profile", data))
    data = example("profile.json")
    data["content"]["as_of_month"] = "2026-13"
    cases.append(("Profile", data))
    data = example("profile.json")
    data["content"]["evidence"][0]["unexpected"] = "must reject"
    cases.append(("Profile", data))
    data = example("profile.json")
    data["content"]["facts"] *= 34  # 102 facts exceeds the schema's 100.
    cases.append(("Profile", data))
    data = example("diagnosis-request.json")
    data["jobs"] *= 6
    cases.append(("DiagnosisCreate", data))
    data = example("diagnosis-request.json")
    data["jobs"] *= 2
    cases.append(("DiagnosisCreate", data))
    data = example("diagnosis-item.json")
    data["score_result"]["score"] = 101
    cases.append(("DiagnosisItem", data))
    data = example("diagnosis-item.json")
    data["score_result"]["assessments"][0]["status"] = "success"
    cases.append(("DiagnosisItem", data))
    data = example("job.json")
    data["content"]["requirements"][0]["target"] = ""
    cases.append(("Job", data))
    for filename, name in EXAMPLES.items():
        data = example(filename)
        data["unexpected"] = "must reject"
        cases.append((name, data))
    return cases


def test_invalid_wire_inputs_rejected_by_both_validators(design, example):
    for name, data in invalid_examples(example):
        with pytest.raises(SchemaError):
            example_validator(design, name).validate(data)
        with pytest.raises(DTOError):
            SCHEMA_MODELS[name].model_validate(data)


def test_nullable_is_still_required(design, example):
    fact = example("profile.json")["content"]["facts"][0]
    assert Fact.model_validate(fact).value is None
    del fact["value"]
    with pytest.raises(DTOError):
        Fact.model_validate(fact)
    with pytest.raises(SchemaError):
        example_validator(design, "Fact").validate(fact)
    task_result = {
        "resource_type": "diagnosis",
        "resource_id": example("diagnosis-item.json")["id"],
        "version": None,
        "assistant_message": None,
    }
    assert TaskResult.model_validate(task_result).version is None
    for value in (0, True, "1"):
        task_result["version"] = value
        with pytest.raises(DTOError):
            TaskResult.model_validate(task_result)
        with pytest.raises(SchemaError):
            example_validator(design, "TaskResult").validate(task_result)


def test_shape_validation_does_not_claim_business_validation(design, example):
    data = example("profile.json")
    data["content"]["facts"][0]["evidence_ids"] = ["missing-evidence"]
    # A shape-valid dangling reference must still be checked by C/M2 before persistence.
    example_validator(design, "Profile").validate(data)
    SCHEMA_MODELS["Profile"].model_validate(data)


def test_all_dto_schema_semantics_and_design_references():
    result = run_checks()
    assert result["schemas"] == len(SCHEMA_MODELS)
    assert result["routes"]["implemented"] == []
    assert result["routes"]["pending"]


def test_required_drift_is_detected(design):
    from app.tools.check_contracts import check_dtos

    broken = copy.deepcopy(design)
    broken["components"]["schemas"]["Fact"]["required"].remove("value")
    with pytest.raises(AssertionError, match="Fact"):
        check_dtos(broken)


def test_uuid_date_time_and_integral_numbers_keep_json_schema_semantics(design, example):
    data = example("profile.json")
    data["version"] = 1.0
    data["created_at"] = "2026-09-24t00:00:00z"
    example_validator(design, "Profile").validate(data)
    dto = SCHEMA_MODELS["Profile"].model_validate(data)
    example_validator(design, "Profile").validate(dto.model_dump(mode="json"))
    data["id"] = data["id"].replace("-", "")
    with pytest.raises(SchemaError):
        example_validator(design, "Profile").validate(data)
    with pytest.raises(DTOError):
        SCHEMA_MODELS["Profile"].model_validate(data)


def test_unique_items_use_json_values_before_parsing(design, example):
    data = example("diagnosis-request.json")
    data["jobs"][0]["id"] = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    other = copy.deepcopy(data["jobs"][0])
    other["id"] = other["id"].upper()
    data["jobs"].append(other)
    example_validator(design, "DiagnosisCreate").validate(data)
    dto = SCHEMA_MODELS["DiagnosisCreate"].model_validate(data)
    example_validator(design, "DiagnosisCreate").validate(dto.model_dump(mode="json"))
    # Same resource with different versions is a business constraint, not uniqueItems.
    data["jobs"][1]["id"] = data["jobs"][0]["id"]
    data["jobs"][1]["version"] = 1.0
    with pytest.raises(SchemaError):
        example_validator(design, "DiagnosisCreate").validate(data)
    with pytest.raises(DTOError):
        SCHEMA_MODELS["DiagnosisCreate"].model_validate(data)
