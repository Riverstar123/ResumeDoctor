"""A consumer can inject a local test double without loading provider settings."""

import asyncio

from app.contracts import ModelMetadata, ProfileContent
from app.contracts.ports import ModelGateway, StructuredResult, TaskContext


def test_gateway_consumer_uses_explicit_context_and_shared_dto(example):
    profile = example("profile.json")["content"]
    metadata = example("diagnosis-item.json")["model_metadata"]

    class LocalGateway:
        async def generate_structured(
            self, task_name, prompt_context, output_schema, timeout_seconds, *, context
        ):
            assert task_name == "profile_extract"
            assert context.model_id == metadata["model_id"]
            assert timeout_seconds == 1
            assert output_schema == ProfileContent.model_json_schema()
            assert prompt_context == {"synthetic": True}
            return StructuredResult(profile, ModelMetadata.model_validate(metadata))

    gateway: ModelGateway = LocalGateway()
    assert isinstance(gateway, ModelGateway)

    async def consume():
        result = await gateway.generate_structured(
            "profile_extract",
            {"synthetic": True},
            ProfileContent.model_json_schema(),
            1,
            context=TaskContext(metadata["model_id"]),
        )
        return ProfileContent.model_validate(dict(result.data))

    assert asyncio.run(consume()).overview == profile["overview"]
