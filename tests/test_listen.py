import asyncio
import contextlib
import inspect
import socket
import threading
import time

import pytest
from pytest_httpserver import HTTPServer
from werkzeug import Request, Response

from eccc_msc_amqp_alerts import listen

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


ROUTING_KEY = "v02.post.20261101.WXO-DD.bulletins.alphanumeric.20261101.SA.CYXC.15"


@pytest.fixture
def dd_host(httpserver: HTTPServer, monkeypatch) -> str:
    """Serves HPFX and DD from one local server under different path prefixes.
    Returns the DD host, which is what messages name as their source."""
    monkeypatch.setattr(listen, "HPFX_HOST", httpserver.url_for("/hpfx/"))
    return httpserver.url_for("/dd/")


def closed_port_host() -> str:
    """A host nothing is listening on, so connections are refused"""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}/"


@contextlib.contextmanager
def hung_host():
    """A host that accepts connections but never answers, like a hung server"""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        yield f"http://127.0.0.1:{sock.getsockname()[1]}/"


@contextlib.contextmanager
def dropping_host(drop_first: int, body: str = BULLETIN):
    """Closes its first `drop_first` connections without answering, like a server
    closing an idle keep-alive connection just as it's reused, then answers normally.
    Yields the host and a list that records each attempt."""
    attempts: list[int] = []
    stop = threading.Event()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        sock.settimeout(0.05)

        def serve():
            while not stop.is_set():
                try:
                    conn, _ = sock.accept()
                except TimeoutError:
                    continue
                with conn:
                    conn.recv(65536)
                    attempts.append(1)
                    if len(attempts) > drop_first:
                        data = body.encode()
                        conn.sendall(
                            b"HTTP/1.1 200 OK\r\nConnection: close\r\n"
                            + f"Content-Length: {len(data)}\r\n\r\n".encode()
                            + data
                        )

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{sock.getsockname()[1]}/", attempts
        finally:
            stop.set()
            thread.join()


@pytest.fixture
def unreachable_host(monkeypatch) -> str:
    """A host nothing is listening on, used for both HPFX and DD"""
    host = closed_port_host()
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

    result = listen.on_bulletin_message(ROUTING_KEY, message_body(dd_host))

    assert await resolve(result) == BULLETIN


async def test_bulletin_message_returns_none_when_hosts_unreachable(
    unreachable_host: str,
):
    result = listen.on_bulletin_message(ROUTING_KEY, message_body(unreachable_host))

    assert await resolve(result) is None


async def test_bulletin_message_returns_none_when_hpfx_and_dd_time_out(monkeypatch):
    monkeypatch.setattr(listen, "FETCH_TIMEOUT_SECS", 0.2)
    with hung_host() as host:
        monkeypatch.setattr(listen, "HPFX_HOST", host)

        result = listen.on_bulletin_message(ROUTING_KEY, message_body(host))

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


async def test_falls_back_to_dd_when_hpfx_unreachable(
    httpserver: HTTPServer, dd_host: str, monkeypatch
):
    monkeypatch.setattr(listen, "HPFX_HOST", closed_port_host())
    httpserver.expect_oneshot_request(f"/dd/{PATH}").respond_with_data(BULLETIN)

    assert await resolve(listen.fetch_bulletin_text(dd_host, PATH)) == BULLETIN
    httpserver.check_assertions()


async def test_falls_back_to_dd_when_hpfx_times_out(
    httpserver: HTTPServer, dd_host: str, monkeypatch
):
    monkeypatch.setattr(listen, "FETCH_TIMEOUT_SECS", 0.2)
    with hung_host() as host:
        monkeypatch.setattr(listen, "HPFX_HOST", host)
        httpserver.expect_oneshot_request(f"/dd/{PATH}").respond_with_data(BULLETIN)

        assert await resolve(listen.fetch_bulletin_text(dd_host, PATH)) == BULLETIN
    httpserver.check_assertions()


async def test_bulletin_dated_end_of_last_month_still_fetched(
    httpserver: HTTPServer, dd_host: str
):
    """Header dates only give the day, so the 31st must decode in any month"""
    path = PATH.replace("SACN43_CYXC_011500", "SACN43_CYXC_311500")
    httpserver.expect_request(f"/hpfx/{path}").respond_with_data(BULLETIN)

    result = listen.on_bulletin_message(ROUTING_KEY, message_body(dd_host, path))

    assert await resolve(result) == BULLETIN


async def test_falls_back_to_dd_quickly_when_hpfx_cannot_connect(
    httpserver: HTTPServer, dd_host: str, monkeypatch
):
    """Connecting includes the TLS handshake, which is where HPFX has been seen to
    hang. That shouldn't hold up every bulletin for the full fetch timeout."""
    monkeypatch.setattr(listen, "FETCH_TIMEOUT_SECS", 5)
    monkeypatch.setattr(listen, "FETCH_CONNECT_TIMEOUT_SECS", 0.2)
    with hung_host() as host:
        # The TCP connection succeeds, but the TLS handshake never completes
        monkeypatch.setattr(listen, "HPFX_HOST", host.replace("http://", "https://"))
        httpserver.expect_oneshot_request(f"/dd/{PATH}").respond_with_data(BULLETIN)

        started = time.monotonic()
        assert await resolve(listen.fetch_bulletin_text(dd_host, PATH)) == BULLETIN
        assert time.monotonic() - started < 2
    httpserver.check_assertions()


async def test_retries_dd_once_when_it_drops_the_connection(monkeypatch):
    monkeypatch.setattr(listen, "HPFX_HOST", closed_port_host())
    with dropping_host(drop_first=1) as (dd, attempts):
        assert await resolve(listen.fetch_bulletin_text(dd, PATH)) == BULLETIN
    assert len(attempts) == 2


async def test_retries_hpfx_before_falling_back_to_dd(monkeypatch):
    with dropping_host(drop_first=1) as (hpfx, attempts):
        monkeypatch.setattr(listen, "HPFX_HOST", hpfx)
        # Any request to DD would be refused
        result = listen.fetch_bulletin_text(closed_port_host(), PATH)

        assert await resolve(result) == BULLETIN
    assert len(attempts) == 2


async def test_gives_up_after_one_retry(monkeypatch):
    with dropping_host(drop_first=99) as (host, attempts):
        monkeypatch.setattr(listen, "HPFX_HOST", host)

        result = listen.on_bulletin_message(ROUTING_KEY, message_body(host))

        assert await resolve(result) is None
    # HPFX and DD are the same server here: 2 attempts each
    assert len(attempts) == 4
