"""Write the API's OpenAPI spec to cli/openapi.json, the source of the CLI's API client. Building
the app does not connect to the database, so the placeholder settings are never used."""

import json

from yaksh.api import create_app
from yaksh.config import REPO_ROOT, Settings

SPEC_PATH = REPO_ROOT / "cli" / "openapi.json"


def main() -> None:
    settings = Settings(
        api_token="unused",
        database_url="postgresql+asyncpg://unused@localhost/unused",
        encryption_key="unused" * 6,
    )
    spec = create_app(settings).openapi()
    SPEC_PATH.parent.mkdir(exist_ok=True)
    SPEC_PATH.write_text(json.dumps(spec, indent=2) + "\n")


if __name__ == "__main__":
    main()
