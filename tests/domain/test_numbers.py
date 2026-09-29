from truman.domain.numbers import PlivoApplication


def application(answer_url: str, hangup_url: str) -> PlivoApplication:
    return PlivoApplication(
        app_id="1",
        name="truman",
        answer_url=answer_url,
        answer_method="POST",
        hangup_url=hangup_url,
        hangup_method="POST",
    )


def test_an_application_url_with_a_trailing_slash_does_not_reach_the_worker() -> None:
    slashed = application("https://t.example/incoming/", "https://t.example/incoming/hangup/")

    assert slashed.problems("https://t.example/") == [
        "Plivo application truman has answer URL 'https://t.example/incoming/'; "
        "set it to 'https://t.example/incoming'",
        "Plivo application truman has hangup URL 'https://t.example/incoming/hangup/'; "
        "set it to 'https://t.example/incoming/hangup'",
    ]
