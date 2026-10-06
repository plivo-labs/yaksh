from collections.abc import Iterator

import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from yaksha.domain.errors import UnavailableError
from yaksha.integrations.s3 import S3FileStore

ACCESS_KEY = "yaksha"
SECRET_KEY = "yaksha-storage"


@pytest.fixture(scope="module")
def endpoint() -> Iterator[str]:
    """The same SeaweedFS the compose file runs."""
    storage = (
        DockerContainer("chrislusf/seaweedfs:4.48")
        .with_command("mini -dir=/data -bucket=yaksha")
        .with_env("AWS_ACCESS_KEY_ID", ACCESS_KEY)
        .with_env("AWS_SECRET_ACCESS_KEY", SECRET_KEY)
        .with_exposed_ports(8333)
        .waiting_for(LogMessageWaitStrategy("created bucket yaksha"))
    )
    with storage:
        yield f"http://{storage.get_container_host_ip()}:{storage.get_exposed_port(8333)}"


async def test_a_file_comes_back_as_it_went_in(endpoint: str) -> None:
    store = S3FileStore(endpoint, "yaksha", ACCESS_KEY, SECRET_KEY)
    data = b"%PDF-1.4 clinic hours"

    await store.put("documents/abc", data, "application/pdf")
    await store.put("documents/abc", data, "application/pdf")

    assert b"".join([chunk async for chunk in store.stream("documents/abc")]) == data


async def test_a_wrong_key_and_a_missing_file_are_reported_as_storage_failures(
    endpoint: str,
) -> None:
    wrong = S3FileStore(endpoint, "yaksha", ACCESS_KEY, "not-the-secret")
    store = S3FileStore(endpoint, "yaksha", ACCESS_KEY, SECRET_KEY)

    with pytest.raises(UnavailableError, match="refused the upload: SignatureDoesNotMatch"):
        await wrong.put("documents/x", b"x", "text/plain")
    with pytest.raises(UnavailableError, match="could not return the file: NoSuchKey"):
        await anext(store.stream("documents/missing"))
