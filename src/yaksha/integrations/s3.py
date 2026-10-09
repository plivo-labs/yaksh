"""The file store over the S3 API: SeaweedFS in the bundled compose file, or any S3-compatible
service a deployment points it at."""

from collections.abc import AsyncGenerator

import aiohttp
from aiobotocore.config import AioConfig
from aiobotocore.session import get_session
from botocore.exceptions import BotoCoreError, ClientError

from yaksha.diagnostics import describe_exception
from yaksha.domain.errors import UnavailableError

CONFIG = AioConfig(connect_timeout=5, read_timeout=30, retries={"max_attempts": 2})
CHUNK_BYTES = 256 * 1024


class S3FileStore:
    def __init__(
        self,
        endpoint: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        *,
        region: str = "us-east-1",
    ) -> None:
        self.bucket = bucket
        self._client_args = {
            "endpoint_url": endpoint,
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
            "region_name": region,
            "config": CONFIG,
        }

    async def put(self, key: str, data: bytes, media_type: str) -> None:
        try:
            async with get_session().create_client("s3", **self._client_args) as client:
                await client.put_object(
                    Bucket=self.bucket, Key=key, Body=data, ContentType=media_type
                )
        except (BotoCoreError, ClientError) as error:
            raise UnavailableError(f"file storage refused the upload: {reason(error)}") from error

    async def get(self, key: str) -> bytes:
        return b"".join([chunk async for chunk in self.stream(key)])

    async def stream(self, key: str) -> AsyncGenerator[bytes]:
        try:
            async with get_session().create_client("s3", **self._client_args) as client:
                response = await client.get_object(Bucket=self.bucket, Key=key)
                async with response["Body"] as body:
                    async for chunk in body.iter_chunks(CHUNK_BYTES):
                        yield chunk
        except (BotoCoreError, ClientError, aiohttp.ClientError) as error:
            raise UnavailableError(
                f"file storage could not return the file: {reason(error)}"
            ) from error


def reason(error: BotoCoreError | ClientError | aiohttp.ClientError) -> str:
    if isinstance(error, ClientError):
        detail = error.response.get("Error", {})
        return f"{detail.get('Code', 'error')}: {detail.get('Message', '')}".rstrip(": ")
    return describe_exception(error)
