from httpx import AsyncClient

from tests.conftest import POOL_APP_ID, POOL_APPLICATION, FakePlivoAccount, FakeProviders
from yaksh.domain.numbers import AccountNumber, PlivoApplication

OTHER_APP = POOL_APPLICATION.model_copy(update={"app_id": "55", "name": "Yaksh-Railway"})
CX_APP = PlivoApplication(
    app_id="77",
    name="agent_flow_18005550102",
    answer_url="https://agentflow.example/answer",
    answer_method="POST",
    hangup_url="https://agentflow.example/hangup",
    hangup_method="POST",
)


async def test_the_account_shows_the_receiving_application_and_why_it_does_not_send_calls_here(
    client: AsyncClient, providers: FakeProviders
) -> None:
    good = (await client.get("/api/v1/phone-account")).json()
    providers.account.applications[POOL_APP_ID] = POOL_APPLICATION.model_copy(
        update={"hangup_method": "GET"}
    )
    wrong = (await client.get("/api/v1/phone-account")).json()

    assert good == {
        "provider": "plivo",
        "credentials_saved": True,
        "application": {
            "id": POOL_APP_ID,
            "name": "Yaksh-Test",
            "answer_url": "http://yaksh.test/incoming",
            "problems": [],
        },
        "test_numbers": 8,
    }
    assert wrong["application"]["problems"] == [
        "Plivo application Yaksh-Test has hangup method 'GET'; set it to 'POST'"
    ]


async def test_choosing_an_application_saves_it_and_its_numbers_become_the_test_numbers(
    client: AsyncClient, providers: FakeProviders
) -> None:
    providers.account = FakePlivoAccount(
        [AccountNumber(number="+18005550100", application_id=OTHER_APP.app_id)],
        applications=[POOL_APPLICATION, OTHER_APP, CX_APP],
    )

    listed = (await client.get("/api/v1/phone-account/applications")).json()
    unknown = await client.put("/api/v1/phone-account/application", json={"application_id": "9"})
    cx = await client.put(
        "/api/v1/phone-account/application", json={"application_id": CX_APP.app_id}
    )
    chosen = await client.put(
        "/api/v1/phone-account/application", json={"application_id": OTHER_APP.app_id}
    )
    stored = (await client.get("/api/v1/settings")).json()["values"]["phone"]
    numbers = (await client.get("/api/v1/phone-numbers")).json()

    assert [application["name"] for application in listed] == ["Yaksh-Railway", "Yaksh-Test"]
    assert (unknown.status_code, cx.status_code, chosen.status_code) == (422, 422, 200)
    assert chosen.json()["test_numbers"] == 1
    assert stored["application_id"] == OTHER_APP.app_id
    assert [(item["number"], item["owner"]) for item in numbers["items"]] == [
        ("+18005550100", "test")
    ]


async def test_yaksh_makes_an_application_for_this_install_and_fixes_one_that_points_elsewhere(
    client: AsyncClient, providers: FakeProviders
) -> None:
    made = await client.post("/api/v1/phone-account/application/new")
    made_id = made.json()["application"]["id"]
    providers.account.applications[made_id] = providers.account.applications[made_id].model_copy(
        update={"answer_url": "https://old.example/incoming"}
    )
    broken = (await client.get("/api/v1/phone-account")).json()["application"]["problems"]
    fixed = await client.post("/api/v1/phone-account/application/fix")

    assert made.status_code == 200
    assert providers.account.applications[made_id].name == "Yaksh"
    assert broken == [
        "Plivo application Yaksh has answer URL 'https://old.example/incoming'; "
        "set it to 'http://yaksh.test/incoming'"
    ]
    assert fixed.json()["application"]["problems"] == []
    assert providers.account.applications[made_id].hangup_url == (
        "http://yaksh.test/incoming/hangup"
    )


async def test_a_failure_at_plivo_answers_503_with_plivos_reason(
    client: AsyncClient, providers: FakeProviders
) -> None:
    providers.account.down = True

    made = await client.post("/api/v1/phone-account/application/new")

    assert made.status_code == 503
    assert made.json()["error"]["message"] == "Plivo did not make the application: Plivo is down"
