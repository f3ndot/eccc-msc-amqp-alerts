import pytest

from eccc_msc_amqp_alerts import listen


@pytest.fixture(autouse=True)
async def close_shared_http_client():
    """Each test runs in its own event loop, and an HTTP client's connections can't be
    reused across loops"""
    yield
    await listen.close_http_client()
