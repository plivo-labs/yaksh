from pydantic import SecretStr

from yaksh.config import Settings
from yaksh.integrations.s3 import S3FileStore


def file_store(settings: Settings) -> S3FileStore:
    return S3FileStore(
        settings.s3_endpoint,
        settings.s3_bucket,
        reveal(settings.s3_access_key),
        reveal(settings.s3_secret_key),
        region=settings.s3_region,
    )


def reveal(secret: SecretStr | None) -> str | None:
    return None if secret is None else secret.get_secret_value()
