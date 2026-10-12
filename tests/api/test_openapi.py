from yaksh.api import create_app
from yaksh.config import Settings

ERROR_BODY = {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}}


def test_every_error_response_has_the_json_error_body(offline_settings: Settings) -> None:
    spec = create_app(offline_settings).openapi()
    errors = {
        (method, path, code): response["content"]
        for path, item in spec["paths"].items()
        for method, operation in item.items()
        for code, response in operation["responses"].items()
        if code[0] in "45"
    }

    assert errors
    assert {key: content for key, content in errors.items() if content != ERROR_BODY} == {}
