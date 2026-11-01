import asyncio
import inspect
import socket
import time

import pika.spec
import pytest
from pytest_httpserver import HTTPServer
from werkzeug import Request, Response

from eccc_msc_amqp_alerts import listen

# Dated the 1st: header decoding assumes the bulletin's day falls in the current
# month, and the 1st is valid in every month
PATH = (
    "20261101/WXO-DD/bulletins/alphanumeric/20261101/SA/CYXC/15/"
    "SACN43_CYXC_011500___12345"
)
BULLETIN = "SACN43 CYXC 011500\nMETAR CYXC 011500Z 27010KT 15SM FEW040 08/M02 A2992="


async def resolve(result):
    """Await `result` if it needs it. Lets these tests run unchanged against both
    blocking and async implementations of the code under test."""
    return await result if inspect.isawaitable(result) else result


def message_body(host: str, path: str = PATH) -> bytes:
    return f"20261101151613.417 {host} {path}".encode()


def deliver(routing_key: str = "v02.post.20261101.WXO-DD.bulletins.alphanumeric"):
    return pika.spec.Basic.Deliver(routing_key=routing_key)


@pytest.fixture
def dd_host(httpserver: HTTPServer, monkeypatch) -> str:
    """Serves HPFX and DD from one local server under different path prefixes.
    Returns the DD host, which is what messages name as their source."""
    monkeypatch.setattr(listen, "HPFX_HOST", httpserver.url_for("/hpfx/"))
    return httpserver.url_for("/dd/")


@pytest.fixture
def unreachable_host(monkeypatch) -> str:
    """A host nothing is listening on, used for both HPFX and DD"""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    host = f"http://127.0.0.1:{port}/"
    monkeypatch.setattr(listen, "HPFX_HOST", host)
    return host


@pytest.fixture(autouse=True)
def clear_recent_bulletins():
    listen.recent_bulletins.clear()


async def test_fetches_from_hpfx_without_touching_dd(
    httpserver: HTTPServer, dd_host: str
):
    httpserver.expect_oneshot_request(
        f"/hpfx/{PATH}", headers={"User-Agent": listen.user_agent}
    ).respond_with_data(BULLETIN)

    assert await resolve(listen.fetch_bulletin_text(dd_host, PATH)) == BULLETIN
    # Fails on any request without a matching expectation, such as one to DD
    httpserver.check_assertions()


async def test_falls_back_to_dd_when_hpfx_fails(httpserver: HTTPServer, dd_host: str):
    httpserver.expect_oneshot_request(f"/hpfx/{PATH}").respond_with_data(
        "not found", status=404
    )
    httpserver.expect_oneshot_request(
        f"/dd/{PATH}", headers={"User-Agent": listen.user_agent}
    ).respond_with_data(BULLETIN)

    assert await resolve(listen.fetch_bulletin_text(dd_host, PATH)) == BULLETIN
    httpserver.check_assertions()


async def test_returns_none_when_hpfx_and_dd_both_fail(
    httpserver: HTTPServer, dd_host: str
):
    httpserver.expect_oneshot_request(f"/hpfx/{PATH}").respond_with_data(
        "not found", status=404
    )
    httpserver.expect_oneshot_request(f"/dd/{PATH}").respond_with_data(
        "server error", status=500
    )

    assert await resolve(listen.fetch_bulletin_text(dd_host, PATH)) is None
    assert list(listen.recent_bulletins) == []
    httpserver.check_assertions()


async def test_prints_and_remembers_fetched_bulletins(
    httpserver: HTTPServer, dd_host: str, capsys
):
    httpserver.expect_request(f"/hpfx/{PATH}").respond_with_data(BULLETIN)

    await resolve(listen.fetch_bulletin_text(dd_host, PATH))

    assert BULLETIN in capsys.readouterr().out
    assert list(listen.recent_bulletins) == [BULLETIN]


async def test_bulletin_message_returns_fetched_text(
    httpserver: HTTPServer, dd_host: str
):
    httpserver.expect_request(f"/hpfx/{PATH}").respond_with_data(BULLETIN)

    result = listen.on_bulletin_message(None, deliver(), None, message_body(dd_host))

    assert await resolve(result) == BULLETIN


async def test_bulletin_message_returns_none_when_hosts_unreachable(
    unreachable_host: str,
):
    result = listen.on_bulletin_message(
        None, deliver(), None, message_body(unreachable_host)
    )

    assert await resolve(result) is None


async def test_bulletin_message_returns_none_on_timeout(
    httpserver: HTTPServer, dd_host: str, monkeypatch
):
    monkeypatch.setattr(listen, "FETCH_TIMEOUT_SECS", 0.2)

    def slow(_request: Request) -> Response:
        time.sleep(1)
        return Response(BULLETIN)

    httpserver.expect_request(f"/hpfx/{PATH}").respond_with_handler(slow)

    result = listen.on_bulletin_message(None, deliver(), None, message_body(dd_host))

    assert await resolve(result) is None


async def test_slow_fetch_does_not_block_the_event_loop(
    httpserver: HTTPServer, dd_host: str
):
    def slow(_request: Request) -> Response:
        time.sleep(0.5)
        return Response(BULLETIN)

    httpserver.expect_request(f"/hpfx/{PATH}").respond_with_handler(slow)

    ticks = 0

    async def tick():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.05)
            ticks += 1

    ticker = asyncio.create_task(tick())
    try:
        assert await resolve(listen.fetch_bulletin_text(dd_host, PATH)) == BULLETIN
    finally:
        ticker.cancel()
    # A blocking fetch would stall the loop for the whole 0.5s, leaving ~0 ticks
    assert ticks >= 5
