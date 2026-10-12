"""Check the design, DTOs, examples and only the routes that have been implemented."""

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from openapi_spec_validator import validate

from app.contracts import SCHEMA_MODELS, SessionCreate
from app.main import create_app
from app.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
EXAMPLES = {
    "profile.json": "Profile",
    "job.json": "Job",
    "diagnosis-request.json": "DiagnosisCreate",
    "diagnosis-item.json": "DiagnosisItem",
}


def load_design(root: Path = REPO_ROOT) -> dict[str, Any]:
    return json.loads((root / "docs/api/openapi.json").read_text(encoding="utf-8"))


def check_references(value: Any, document: dict[str, Any]) -> None:
    if isinstance(value, dict):
        if "$ref" in value:
            ref = value["$ref"]
            if not ref.startswith("#/"):
                raise ValueError(f"external reference is not allowed: {ref}")
            target = document
            for segment in ref[2:].split("/"):
                target = target[segment.replace("~1", "/").replace("~0", "~")]
        for child in value.values():
            check_references(child, document)
    elif isinstance(value, list):
        for child in value:
            check_references(child, document)


def schema_semantics(value: Any, document: dict[str, Any]) -> Any:
    """Ignore presentation/ref names; preserve validation keywords and requirements."""
    if not isinstance(value, dict):
        return value
    if "$ref" in value:
        target = document
        for segment in value["$ref"][2:].split("/"):
            target = target[segment.replace("~1", "/").replace("~0", "~")]
        return schema_semantics(
            {**target, **{k: v for k, v in value.items() if k != "$ref"}}, document
        )
    result = {}
    for key, item in value.items():
        if key in {"title", "description", "examples", "example", "default", "$defs", "$schema"}:
            continue
        if key == "properties":
            result[key] = {name: schema_semantics(child, document) for name, child in item.items()}
        elif key in {"anyOf", "oneOf", "allOf"}:
            result[key] = sorted(
                [schema_semantics(child, document) for child in item],
                key=lambda child: json.dumps(child, sort_keys=True),
            )
        elif key in {"required", "enum"}:
            result[key] = sorted(item, key=lambda child: json.dumps(child, sort_keys=True))
        elif key == "const":
            result["enum"] = [item]
        elif key == "type" and isinstance(item, list):
            # The design uses type arrays; Pydantic emits equivalent anyOf branches.
            result["anyOf"] = sorted(
                [
                    schema_semantics(
                        {
                            k: v
                            for k, v in {**value, "type": t}.items()
                            if not (
                                t == "null"
                                and k in {"pattern", "minLength", "maxLength", "minimum", "maximum"}
                            )
                        },
                        document,
                    )
                    for t in item
                ],
                key=lambda child: json.dumps(child, sort_keys=True),
            )
            return result
        elif isinstance(item, dict):
            result[key] = schema_semantics(item, document)
        else:
            result[key] = item
    return result


def example_validator(design: dict[str, Any], name: str) -> Draft202012Validator:
    return Draft202012Validator(
        {"$ref": f"#/components/schemas/{name}", "components": design["components"]},
        format_checker=FormatChecker(),
    )


def check_dtos(design: dict[str, Any]) -> None:
    expected = design["components"]["schemas"]
    if set(expected) != set(SCHEMA_MODELS):
        raise AssertionError("DTO registry differs from the design schema set")
    for name, model in SCHEMA_MODELS.items():
        generated = model.model_json_schema()
        if schema_semantics(expected[name], design) != schema_semantics(generated, generated):
            raise AssertionError(f"DTO schema drift: {name}")
    session_schema = design["paths"]["/session"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]
    generated = SessionCreate.model_json_schema()
    if schema_semantics(session_schema, design) != schema_semantics(generated, generated):
        raise AssertionError("DTO schema drift: SessionCreate (inline request)")


def operations(
    document: dict[str, Any],
    prefix: str = "",
) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (
            path.removeprefix(prefix) if prefix and path.startswith(prefix + "/") else path,
            method,
        ): operation
        for path, methods in document["paths"].items()
        for method, operation in methods.items()
        if method in HTTP_METHODS
    }


def compare_routes(
    design: dict[str, Any],
    generated: dict[str, Any],
    *,
    operational_routes: frozenset[tuple[str, str]] = frozenset({("/healthz", "get")}),
) -> dict[str, list[str]]:
    prefix = design["servers"][0]["url"].rstrip("/")
    expected, actual = operations(design), operations(generated, prefix=prefix)
    implemented, operational = [], []
    for key, route in actual.items():
        path, method = key
        label = f"{method.upper()} {path}"
        if key in operational_routes:
            operational.append(label)
            continue
        if key not in expected:
            raise AssertionError(f"undocumented business route: {label}")
        reference = expected[key]
        for field in ["requestBody", "responses", "parameters"]:
            left, right = reference.get(field), route.get(field)
            if field == "parameters":
                # Parameter order is immaterial; required and all schema constraints are not.
                left = sorted(left or [], key=lambda p: (p["in"], p["name"]))
                right = sorted(right or [], key=lambda p: (p["in"], p["name"]))

            def normalize(value: Any, doc: dict[str, Any]) -> Any:
                if isinstance(value, list):
                    return [normalize(x, doc) for x in value]
                if isinstance(value, dict):
                    if "$ref" in value or "type" in value or "properties" in value:
                        return schema_semantics(value, doc)
                    return {
                        k: normalize(v, doc)
                        for k, v in value.items()
                        if k not in {"description", "title", "examples", "example"}
                    }
                return value

            if normalize(left, design) != normalize(right, generated):
                raise AssertionError(f"route drift: {label} {field}")
        if reference.get("security", design.get("security", [])) != route.get(
            "security", generated.get("security", [])
        ):
            raise AssertionError(f"route drift: {label} security")
        for alternative in reference.get("security", design.get("security", [])):
            for scheme in alternative:
                left = design["components"]["securitySchemes"][scheme]
                right = generated.get("components", {}).get("securitySchemes", {}).get(scheme)
                if schema_semantics(left, design) != schema_semantics(right, generated):
                    raise AssertionError(f"route drift: {label} security scheme {scheme}")
        implemented.append(label)
    pending = [f"{method.upper()} {path}" for path, method in expected.keys() - actual.keys()]
    return {
        "implemented": sorted(implemented),
        "pending": sorted(pending),
        "operational": sorted(operational),
    }


def run_checks(root: Path = REPO_ROOT) -> dict[str, Any]:
    design = load_design(root)
    check_references(design, design)
    validate(design)
    check_dtos(design)
    for filename, name in EXAMPLES.items():
        data = json.loads((root / "docs/examples" / filename).read_text(encoding="utf-8"))
        example_validator(design, name).validate(data)
        parsed = SCHEMA_MODELS[name].model_validate(data)
        example_validator(design, name).validate(parsed.model_dump(mode="json"))
    generated = create_app(Settings(_env_file=None)).openapi()
    return {
        "schemas": len(SCHEMA_MODELS),
        "examples": len(EXAMPLES),
        "routes": compare_routes(design, generated),
    }


if __name__ == "__main__":
    print(json.dumps(run_checks(), ensure_ascii=False, indent=2))
