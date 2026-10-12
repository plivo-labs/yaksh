"""The file store over the S3 API: SeaweedFS in the bundled compose file, or any S3-compatible
service a deployment points it at. Without an endpoint it is AWS S3, and without keys botocore
finds the credentials itself, from an IAM role for example."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack

import aiohttp
from aiobotocore.client import AioBaseClient
from aiobotocore.config import AioConfig
from aiobotocore.session import get_session
from botocore.exceptions import BotoCoreError, ClientError

from yaksh.diagnostics import describe_exception
from yaksh.domain.errors import UnavailableError

CONFIG = AioConfig(
    connect_timeout=5, read_timeout=30, retries={"max_attempts": 2}, max_pool_connections=50
)
"""A request waits without a time limit for a free connection, so the pool is sized well above
the downloads one process serves at once."""
CHUNK_BYTES = 256 * 1024


class S3FileStore:
    """Holds one client, made at the first operation, so its connections are reused until
    close()."""

    def __init__(
        self,
        endpoint: str | None,
        bucket: str,
        access_key: str | None,
        secret_key: str | None,
        *,
        region: str = "us-east-1",
    ) -> None:
        self.bucket = bucket
        self.location = endpoint or "AWS S3"
        self._client_args = {
            "endpoint_url": endpoint,
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
            "region_name": region,
            "config": CONFIG,
        }
        self._client: AioBaseClient | None = None
        self._opening = asyncio.Lock()
        self._open = AsyncExitStack()

    async def _connected(self) -> AioBaseClient:
        async with self._opening:
            if self._client is None:
                self._client = await self._open.enter_async_context(
                    get_session().create_client("s3", **self._client_args)
                )
            return self._client

    async def close(self) -> None:
        async with self._opening:
            await self._open.aclose()
            self._client = None

    async def check(self) -> None:
        """Reaches the bucket with the configured credentials. HeadBucket needs s3:ListBucket."""
        try:
            client = await self._connected()
            await client.head_bucket(Bucket=self.bucket)
        except (BotoCoreError, ClientError) as error:
            raise UnavailableError(
                f"cannot use bucket {self.bucket!r} at {self.location}: {reason(error)}"
            ) from error

    async def put(self, key: str, data: bytes, media_type: str) -> None:
        try:
            client = await self._connected()
            await client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=media_type)
        except (BotoCoreError, ClientError) as error:
            raise UnavailableError(f"file storage refused the upload: {reason(error)}") from error

    async def get(self, key: str) -> bytes:
        return b"".join([chunk async for chunk in self.stream(key)])

    async def stream(self, key: str) -> AsyncGenerator[bytes]:
        try:
            client = await self._connected()
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
