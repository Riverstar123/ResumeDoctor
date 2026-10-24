"""HTTP human writes cannot invent or alter M3's document/message evidence.

Both API adapters are exercised. PostgreSQL tests own their sessions and preserve
other test/browser data; internal trusted-output seeding represents the worker
boundary, whose real M3 path is separately covered by test_int02.py.
"""

import asyncio
import copy
import os
from contextlib import AsyncExitStack, asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.contracts import Profile, ProfileContent
from app.llm.synthetic import synthetic_profile_payload
from app.main import create_app
from app.platform.repositories import InMemoryRepository, Versioned
from app.settings import Settings

from .test_api import ORIGIN, check, post, session


@pytest.fixture(params=["memory", "postgres"])
def stack(request, tmp_path):
    engine = None
    sessions = []
    if request.param == "postgres":
        sa = pytest.importorskip("sqlalchemy")
        from app.database import create_app as database_app
        from app.platform.repositories import PostgreSQLRepository

        url = os.environ.get("RD_TEST_DATABASE_URL")
        if not url:
            pytest.skip("RD_TEST_DATABASE_URL is required for PostgreSQL source guards")
        parsed = sa.engine.make_url(url)
        assert parsed.get_backend_name() == "postgresql"
        assert parsed.database and "test" in parsed.database.lower()
        engine = sa.create_engine(url, hide_parameters=True)
        with engine.connect() as connection:
            assert connection.scalar(sa.text("SELECT version()")).startswith("PostgreSQL")
            assert connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
        repo = PostgreSQLRepository(engine)
        app = database_app(Settings(_env_file=None, upload_dir=tmp_path), repository=repo)
    else:
        repo = InMemoryRepository()
        app = create_app(Settings(_env_file=None), repository=repo)
    create_session = repo.create_session

    def tracked_session():
        record, token = create_session()
        sessions.append(record.public.id)
        return record, token

    repo.create_session = tracked_session

    def seed(sid, source_type):
        content = ProfileContent.model_validate(synthetic_profile_payload())
        source_id = str(uuid4())
        for evidence in content.evidence:
            evidence.source_type = source_type
            evidence.source_id = source_id
            evidence.locator = "段落 1" if source_type == "document" else None
        if engine is not None:
            with engine.begin() as connection:
                repo._active(connection, sid)
                profile = repo._create_versioned(connection, repo.profiles, sid, content)
        else:
            profile = Profile(
                id=str(uuid4()), version=1, confirmed=False, content=content, created_at=repo.now()
            )
            repo.profiles[profile.id] = Versioned(sid, [profile.model_copy(deep=True)])
        return profile.model_dump(mode="json")

    yield SimpleNamespace(app=app, repo=repo, seed=seed, engine=engine)
    for sid in sessions:
        repo.revoke(sid)
    if engine is not None:
        repo.retry_file_cleanup(tmp_path)
        repo.close()


@asynccontextmanager
async def clients_for(stack, number=1):
    async with AsyncExitStack() as context:
        clients = [
            await context.enter_async_context(
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=stack.app),
                    base_url="http://test",
                    headers={"Origin": ORIGIN},
                )
            )
            for _ in range(number)
        ]
        yield clients


def manual_content():
    content = synthetic_profile_payload()
    for evidence in content["evidence"]:
        evidence["source_type"] = "manual"
    return content


@pytest.mark.parametrize("source_type", ["document", "message"])
def test_create_rejects_unverified_source_and_does_not_consume_idempotency_key(stack, source_type):
    async def run():
        async with clients_for(stack) as (client,):
            await session(client)
            content = manual_content()
            for evidence in content["evidence"]:
                evidence.update(source_type=source_type, source_id=str(uuid4()), quote="伪造原文")
            key = str(uuid4())
            check(
                await post(client, "/api/v1/profiles", {"content": content}, key=key),
                422,
                code="VALIDATION_ERROR",
            )
            created = check(
                await post(client, "/api/v1/profiles", {"content": manual_content()}, key=key),
                201,
                "Profile",
            )
            assert created["version"] == 1

    asyncio.run(run())


def test_manual_sources_remain_editable_but_cannot_be_promoted_to_document(stack):
    async def run():
        async with clients_for(stack) as (client,):
            await session(client)
            created = check(
                await post(client, "/api/v1/profiles", {"content": manual_content()}),
                201,
                "Profile",
            )
            content = copy.deepcopy(created["content"])
            content["evidence"][0].update(
                quote="用户重新输入的手工证据", source_id="manual-revision-2"
            )
            content["facts"][0]["label"] = "用户更正的项目"
            updated = check(
                await client.put(
                    f"/api/v1/profiles/{created['id']}",
                    json={"base_version": 1, "content": content},
                ),
                200,
                "Profile",
            )
            assert updated["version"] == 2 and updated["content"] == content
            promoted = copy.deepcopy(content)
            promoted["evidence"][0]["source_type"] = "document"
            check(
                await client.put(
                    f"/api/v1/profiles/{created['id']}",
                    json={"base_version": 2, "content": promoted},
                ),
                422,
                code="VALIDATION_ERROR",
            )
            assert (
                check(await client.get(f"/api/v1/profiles/{created['id']}"), 200, "Profile")
                == updated
            )

    asyncio.run(run())


@pytest.mark.parametrize("source_type", ["document", "message"])
@pytest.mark.parametrize(
    "attack", ["quote", "source_id", "source_type", "locator", "local_id", "new"]
)
def test_update_preserves_trusted_source_records_atomically(stack, source_type, attack):
    async def run():
        async with clients_for(stack) as (client,):
            sid = (await session(client))["id"]
            profile = stack.seed(sid, source_type)
            content = copy.deepcopy(profile["content"])
            evidence = content["evidence"][0]
            if attack == "quote":
                evidence["quote"] = "原始材料里没有的证据"
            elif attack == "source_id":
                evidence["source_id"] = str(uuid4())
            elif attack == "source_type":
                evidence["source_type"] = "manual"
            elif attack == "locator":
                evidence["locator"] = "伪造定位"
            elif attack == "local_id":
                old_id = evidence["id"]
                evidence["id"] = "copied-evidence"
                for fact in content["facts"]:
                    fact["evidence_ids"] = [
                        "copied-evidence" if value == old_id else value
                        for value in fact["evidence_ids"]
                    ]
            else:
                content["evidence"].append(
                    {
                        "id": "unverified-new",
                        "source_type": source_type,
                        "source_id": str(uuid4()),
                        "quote": "不能伪造新的原文",
                        "locator": None,
                    }
                )
            check(
                await client.put(
                    f"/api/v1/profiles/{profile['id']}",
                    json={"base_version": 1, "content": content},
                ),
                422,
                code="VALIDATION_ERROR",
            )
            assert (
                check(await client.get(f"/api/v1/profiles/{profile['id']}"), 200, "Profile")
                == profile
            )
            # Rejection must leave the base version usable, with verified evidence intact.
            edited = copy.deepcopy(profile["content"])
            edited["overview"] = "用户可以正常编辑事实概述"
            valid = check(
                await client.put(
                    f"/api/v1/profiles/{profile['id']}", json={"base_version": 1, "content": edited}
                ),
                200,
                "Profile",
            )
            assert valid["version"] == 2
            assert valid["content"]["evidence"] == profile["content"]["evidence"]

    asyncio.run(run())


@pytest.mark.parametrize("source_type", ["document", "message"])
def test_sources_from_another_session_cannot_be_copied_into_create_or_update(stack, source_type):
    async def run():
        async with clients_for(stack, 2) as (owner, attacker):
            owner_sid = (await session(owner))["id"]
            attacker_sid = (await session(attacker))["id"]
            donor = stack.seed(owner_sid, source_type)
            recipient = stack.seed(attacker_sid, source_type)
            check(
                await post(attacker, "/api/v1/profiles", {"content": donor["content"]}),
                422,
                code="VALIDATION_ERROR",
            )
            check(
                await attacker.put(
                    f"/api/v1/profiles/{recipient['id']}",
                    json={"base_version": 1, "content": donor["content"]},
                ),
                422,
                code="VALIDATION_ERROR",
            )
            check(
                await attacker.get(f"/api/v1/profiles/{donor['id']}"),
                404,
                code="RESOURCE_NOT_FOUND",
            )
            assert (
                check(await attacker.get(f"/api/v1/profiles/{recipient['id']}"), 200, "Profile")
                == recipient
            )

    asyncio.run(run())


@pytest.mark.parametrize("source_type", ["document", "message"])
def test_removal_and_manual_replacement_are_allowed_without_rewriting_history(stack, source_type):
    async def run():
        async with clients_for(stack) as (client,):
            sid = (await session(client))["id"]
            original = stack.seed(sid, source_type)
            content = copy.deepcopy(original["content"])
            removed_id = content["evidence"][0]["id"]
            content["facts"] = [f for f in content["facts"] if removed_id not in f["evidence_ids"]]
            content["evidence"] = [e for e in content["evidence"] if e["id"] != removed_id]
            changed = check(
                await client.put(
                    f"/api/v1/profiles/{original['id']}",
                    json={"base_version": 1, "content": content},
                ),
                200,
                "Profile",
            )
            manual = copy.deepcopy(original["content"]["evidence"][0])
            manual.update(
                id="new-manual",
                source_type="manual",
                source_id="manual-revision-2",
                quote="用户补充的新证据",
                locator=None,
            )
            content["evidence"].append(manual)
            restored = check(
                await client.put(
                    f"/api/v1/profiles/{original['id']}",
                    json={"base_version": changed["version"], "content": content},
                ),
                200,
                "Profile",
            )
            assert restored["version"] == 3
            assert (
                check(
                    await client.get(f"/api/v1/profiles/{original['id']}?version=1"), 200, "Profile"
                )
                == original
            )

    asyncio.run(run())
