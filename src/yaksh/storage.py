from yaksh.config import Settings
from yaksh.integrations.s3 import S3FileStore


def file_store(settings: Settings) -> S3FileStore:
    return S3FileStore(
        settings.s3_endpoint,
        settings.s3_bucket,
        settings.s3_access_key.get_secret_value(),
        settings.s3_secret_key.get_secret_value(),
        region=settings.s3_region,
    )
