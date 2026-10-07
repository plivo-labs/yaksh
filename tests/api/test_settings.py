from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from tests.conftest import (
    ENCRYPTION_KEY,
    Db,
    FakeProvider,
    create_agent_id,
    create_scenario,
    new_persona_id,
    save_settings,
    start_run,
)
from yaksha.integrations import provider_checks
from yaksha.integrations.provider_checks import ProviderCheckError
from yaksha.settings import store
from yaksha.settings.cipher import Cipher, SecretUnreadableError

LLM_KEY = "sk-live-0123456789abcdef"


@pytest.fixture
def checks(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, tuple[Any, ...]]]:
    """Provider checks that pass and record what they were asked; a key starting with "bad"
    is refused."""
    asked: list[tuple[str, tuple[Any, ...]]] = []

    def fake(name: str) -> Any:
        async def check(*args: Any) -> Any:
            asked.append((name, args))
            if any(isinstance(arg, str) and arg.startswith("bad") for arg in args):
                raise ProviderCheckError("401 Unauthorized")
            return 3 if name == "check_plivo" else ["gpt-6-luna"]

        return check

    for name in ("llm_models", "check_llm", "check_deepgram", "check_elevenlabs", "check_plivo"):
        monkeypatch.setattr(provider_checks, name, fake(name))
    return asked


async def test_a_saved_key_is_never_returned_and_is_stored_encrypted(
    client: AsyncClient, db: Db, checks: list[Any]
) -> None:
    saved = await client.put("/api/v1/settings/secrets/llm_api_key", json={"value": LLM_KEY})
    listed = await client.get("/api/v1/settings")
    async with db() as session:
        stored = (await session.execute(text("SELECT secrets::text FROM app_settings"))).scalar()

    assert saved.status_code == 200, saved.text
    assert listed.json()["secrets"]["llm_api_key"] == {"hint": "cdef"}
    assert LLM_KEY not in saved.text + listed.text
    assert stored is not None and LLM_KEY not in stored


async def test_a_key_the_provider_refuses_is_not_saved(
    client: AsyncClient, checks: list[Any]
) -> None:
    before = (await client.get("/api/v1/settings")).json()
    refused = await client.put("/api/v1/settings/secrets/deepgram_api_key", json={"value": "bad"})

    assert refused.status_code == 422
    assert "401 Unauthorized" in refused.json()["error"]["message"]
    assert (await client.get("/api/v1/settings")).json() == before


async def test_moving_to_another_plivo_account_checks_both_new_halves_together(
    client: AsyncClient, checks: list[tuple[str, tuple[Any, ...]]]
) -> None:
    moved = await client.put(
        "/api/v1/settings/plivo", json={"auth_id": "MANEW", "auth_token": "new-token"}
    )
    refused = await client.put(
        "/api/v1/settings/plivo", json={"auth_id": "MANEW", "auth_token": "bad-token"}
    )

    assert moved.status_code == 200, moved.text
    assert checks == [
        ("check_plivo", ("MANEW", "new-token")),
        ("check_plivo", ("MANEW", "bad-token")),
    ]
    assert refused.status_code == 422 and "nothing was saved" in refused.text


async def test_a_new_base_url_removes_the_key_unless_the_same_change_saves_one(
    client: AsyncClient, db: Db, checks: list[Any]
) -> None:
    values = (await client.get("/api/v1/settings")).json()["values"]
    values["llm"]["base_url"] = "https://elsewhere.example/v1"

    moved = await client.put("/api/v1/settings/values", json=values)
    test = await client.post("/api/v1/settings/providers/llm/test")
    document = (
        "llm:\n  base_url: https://gateway.example/v1\n"
        "secrets:\n  llm_api_key: sk-gateway-0123456789\n"
    )
    both = await client.post("/api/v1/settings/import", json={"document": document})

    assert "llm_api_key" not in moved.json()["secrets"]
    assert "deepgram_api_key" in moved.json()["secrets"]
    assert test.json() == {
        "provider": "llm",
        "ok": False,
        "detail": "the LLM provider key is not saved",
    }
    assert both.json()["settings"]["secrets"]["llm_api_key"] == {"hint": "6789"}
    assert ("llm_models", ("https://gateway.example/v1", "sk-gateway-0123456789")) in checks


async def test_a_run_cannot_start_while_a_caller_key_is_missing(client: AsyncClient) -> None:
    agent_id = await create_agent_id(client)
    scenario = await create_scenario(client, agent_id, persona_id=await new_persona_id(client))
    await client.delete("/api/v1/settings/secrets/deepgram_api_key")

    refused = await start_run(client, agent_id, [scenario["id"]])

    assert refused.status_code == 422
    assert "add the Deepgram key in Settings" in refused.text


async def test_a_stored_value_this_release_refuses_falls_back_to_its_default(
    client: AsyncClient, db: Db
) -> None:
    async with db() as session:
        await session.execute(
            text(
                'UPDATE app_settings SET values = \'{"limits": {"max_run_repeats": 999999,'
                ' "default_max_turns": 7}}\', version = version + 1'
            )
        )
        await session.commit()

    listed = await client.get("/api/v1/settings")

    assert listed.status_code == 200, listed.text
    limits = listed.json()["values"]["limits"]
    assert (limits["max_run_repeats"], limits["default_max_turns"]) == (10, 7)


async def test_a_changed_value_applies_to_the_next_request_without_a_restart(
    client: AsyncClient,
) -> None:
    values = (await client.get("/api/v1/settings")).json()["values"]
    values["limits"]["default_max_turns"] = 7

    saved = await client.put("/api/v1/settings/values", json=values)
    defaults = await client.get("/api/v1/defaults")

    assert saved.status_code == 200, saved.text
    assert defaults.json()["max_turns"] == 7


async def test_a_value_out_of_range_is_refused_and_nothing_changes(client: AsyncClient) -> None:
    before = (await client.get("/api/v1/settings")).json()
    values = {**before["values"], "phone": {**before["values"]["phone"], "timezone": "Mars/Base"}}

    refused = await client.put("/api/v1/settings/values", json=values)

    assert refused.status_code == 422
    assert (await client.get("/api/v1/settings")).json() == before


async def test_a_run_cannot_start_while_the_plivo_keys_are_missing(client: AsyncClient) -> None:
    agent_id = await create_agent_id(client)
    scenario = await create_scenario(client, agent_id, persona_id=await new_persona_id(client))
    await client.delete("/api/v1/settings/secrets/plivo_auth_token")

    refused = await start_run(client, agent_id, [scenario["id"]])

    assert refused.status_code == 422
    assert "add the Plivo Auth ID and Auth token in Settings" in refused.text


async def test_trigger_secrets_are_listed_by_name_and_removed(client: AsyncClient) -> None:
    await client.put("/api/v1/settings/trigger-secrets/CRM_TOKEN", json={"value": "crm-0123456789"})
    bad_name = await client.put("/api/v1/settings/trigger-secrets/crm", json={"value": "x"})
    listed = (await client.get("/api/v1/settings")).json()["trigger_secrets"]
    await client.delete("/api/v1/settings/trigger-secrets/CRM_TOKEN")

    assert bad_name.status_code == 422
    assert listed == {"CRM_TOKEN": {"hint": "6789"}}
    assert (await client.get("/api/v1/settings")).json()["trigger_secrets"] == {}


async def test_a_new_signing_key_is_shown_once(client: AsyncClient) -> None:
    created = (await client.post("/api/v1/settings/signing-key")).json()["key"]
    listed = await client.get("/api/v1/settings")

    assert created.startswith("whsec_")
    assert listed.json()["secrets"]["trigger_signing_key"] == {"hint": created[-4:]}
    assert created not in listed.text


async def test_the_test_button_reports_a_failure_without_raising(
    client: AsyncClient, db: Db, checks: list[Any]
) -> None:
    await client.delete("/api/v1/settings/secrets/elevenlabs_api_key")
    missing = await client.post("/api/v1/settings/providers/elevenlabs/test")
    await save_settings(db, secrets={"elevenlabs_api_key": "bad-key"})
    refused = await client.post("/api/v1/settings/providers/elevenlabs/test")
    plivo = await client.post("/api/v1/settings/providers/plivo/test")

    assert missing.json() == {
        "provider": "elevenlabs",
        "ok": False,
        "detail": "the ElevenLabs key is not saved",
    }
    assert refused.json()["ok"] is False and "401" in refused.json()["detail"]
    assert plivo.json()["ok"] is True and "3 numbers" in plivo.json()["detail"]


async def test_the_efforts_of_a_model_come_from_the_provider(
    client: AsyncClient, db: Db, provider: tuple[str, FakeProvider]
) -> None:
    base, fake = provider
    await save_settings(db, {"llm": {"base_url": f"{base}/v1"}}, {"llm_api_key": LLM_KEY})

    reasoning = (await client.get("/api/v1/settings/models/gpt-6-luna/efforts")).json()
    fake.reasoning = False
    plain = (await client.get("/api/v1/settings/models/gpt-4.1/efforts")).json()

    assert reasoning["efforts"] == list(provider_checks.REASONING_EFFORTS)
    assert plain == {"model": "gpt-4.1", "efforts": []}


async def test_an_export_names_each_saved_secret_and_never_holds_its_value(
    client: AsyncClient, db: Db
) -> None:
    await save_settings(db, {"caller": {"model": "gpt-6-astra"}}, {"llm_api_key": LLM_KEY})
    await client.put("/api/v1/settings/trigger-secrets/CRM_TOKEN", json={"value": "crm-secret"})

    exported = (await client.get("/api/v1/settings/export")).text

    assert "model: gpt-6-astra" in exported
    assert "llm_api_key: ${LLM_API_KEY}" in exported
    assert "CRM_TOKEN: ${TRIGGER_CRM_TOKEN}" in exported
    assert LLM_KEY not in exported and "crm-secret" not in exported
    assert "deepgram-test-key" not in exported


async def test_an_exported_document_restores_the_settings_with_the_keys_from_env(
    client: AsyncClient, db: Db, checks: list[Any]
) -> None:
    await save_settings(db, {"limits": {"max_run_repeats": 4}}, {"llm_api_key": LLM_KEY})
    document = (await client.get("/api/v1/settings/export")).text
    await save_settings(db, {"limits": {"max_run_repeats": 10}}, {"llm_api_key": None})

    imported = await client.post(
        "/api/v1/settings/import", json={"document": document, "env": {"LLM_API_KEY": LLM_KEY}}
    )

    assert imported.status_code == 200, imported.text
    settings = imported.json()["settings"]
    assert settings["values"]["limits"]["max_run_repeats"] == 4
    assert settings["secrets"]["llm_api_key"] == {"hint": "cdef"}
    assert imported.json()["changes"] == [
        "limits.max_run_repeats: 10 -> 4",
        "llm_api_key: added",
    ]


async def test_a_dry_run_lists_the_changes_and_skips_secrets_it_cannot_resolve(
    client: AsyncClient, checks: list[Any]
) -> None:
    before = (await client.get("/api/v1/settings")).json()
    document = "caller:\n  model: gpt-6-astra\nsecrets:\n  llm_api_key: ${LLM_API_KEY}\n"

    preview = await client.post(
        "/api/v1/settings/import", json={"document": document, "dry_run": True}
    )

    assert preview.json()["changes"] == ["caller.model: gpt-6-luna -> gpt-6-astra"]
    assert preview.json()["skipped"] == ["llm_api_key (${LLM_API_KEY})"]
    assert checks == []
    assert (await client.get("/api/v1/settings")).json() == before


async def test_a_dry_run_leaves_out_a_secret_that_is_already_saved(
    client: AsyncClient, db: Db
) -> None:
    await save_settings(db, secrets={"llm_api_key": LLM_KEY})
    document = "secrets:\n  llm_api_key: ${LLM_API_KEY}\n  typesafe_api_key: ${TYPESAFE_KEY}\n"

    preview = await client.post(
        "/api/v1/settings/import",
        json={
            "document": document,
            "env": {"LLM_API_KEY": LLM_KEY, "TYPESAFE_KEY": "ts-0123456789"},
            "dry_run": True,
        },
    )

    assert preview.json()["changes"] == ["typesafe_api_key: added"]


async def test_an_import_with_a_refused_key_saves_nothing(
    client: AsyncClient, checks: list[Any]
) -> None:
    before = (await client.get("/api/v1/settings")).json()
    document = "caller:\n  model: gpt-6-astra\nsecrets:\n  deepgram_api_key: bad-key\n"

    refused = await client.post("/api/v1/settings/import", json={"document": document})

    assert refused.status_code == 422
    assert "nothing was saved" in refused.json()["error"]["message"]
    assert (await client.get("/api/v1/settings")).json() == before


@pytest.mark.parametrize(
    ("document", "reason"),
    [
        ("caller: [1, 2]", "caller: must be a mapping"),
        ("callers:\n  model: x", "callers: no such section"),
        ("secrets:\n  openai_key: x", "openai_key: no such secret"),
        ("caller:\n  model: x\n  temperature: 1", "temperature"),
        ("{", "not valid YAML"),
        ("trigger_secrets:\n  TOKEN: ''", "1 to 4000 characters"),
    ],
)
async def test_an_import_names_what_is_wrong(
    client: AsyncClient, document: str, reason: str
) -> None:
    refused = await client.post(
        "/api/v1/settings/import", json={"document": document, "dry_run": True}
    )

    assert refused.status_code == 422
    assert reason in refused.json()["error"]["message"]


async def test_settings_saved_with_another_encryption_key_cannot_be_read(
    client: AsyncClient, db: Db
) -> None:
    await save_settings(db, secrets={"llm_api_key": LLM_KEY})

    async with db() as session:
        with pytest.raises(SecretUnreadableError, match="YAKSHA_ENCRYPTION_KEY"):
            await store.load(session, Cipher("another-encryption-key-of-32-chars!!"))
        assert (await store.load(session, Cipher(ENCRYPTION_KEY))).secrets.llm_api_key


def test_an_encrypted_secret_cannot_be_moved_to_another_setting() -> None:
    cipher = Cipher(ENCRYPTION_KEY)
    sealed = cipher.encrypt("llm_api_key", LLM_KEY)

    assert cipher.decrypt("llm_api_key", sealed) == LLM_KEY
    with pytest.raises(SecretUnreadableError):
        cipher.decrypt("trigger:LEAK", sealed)
