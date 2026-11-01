import asyncio
from dataclasses import dataclass, field

import pytest

from eccc_msc_amqp_alerts import message_consumer
from eccc_msc_amqp_alerts.message_consumer import MessageConsumer

ROUTING_KEY = "v02.post.20261031.WXO-DD.bulletins.alphanumeric.20261031.SA.CYXC.15"
BODY = b"20261031151613.417 https://dd.weather.gc.ca/ some/path"


@dataclass
class FakeMessage:
    """The parts of an aio-pika incoming message the consumer uses"""

    routing_key: str = ROUTING_KEY
    body: bytes = BODY


async def test_passes_callback_result_to_on_any_message():
    received = []
    consumer = MessageConsumer(on_any_message=lambda *args: received.append(args))

    await consumer._handle_message(lambda key, body: "bulletin", FakeMessage())

    assert received == [(ROUTING_KEY, BODY, "bulletin")]


async def test_passes_routing_key_and_body_to_callback():
    calls = []
    consumer = MessageConsumer()

    await consumer._handle_message(lambda *args: calls.append(args), FakeMessage())

    assert calls == [(ROUTING_KEY, BODY)]


async def test_counts_messages_per_routing_key():
    consumer = MessageConsumer()

    for _ in range(3):
        await consumer._handle_message(lambda key, body: None, FakeMessage())

    assert consumer.stats.routing_keys[ROUTING_KEY] == 3


async def test_awaits_async_callbacks_before_on_any_message():
    received = []
    consumer = MessageConsumer(on_any_message=lambda *args: received.append(args))

    async def callback(key, body):
        return "fetched bulletin"

    await consumer._handle_message(callback, FakeMessage())

    assert received == [(ROUTING_KEY, BODY, "fetched bulletin")]


async def test_logs_callback_errors_instead_of_raising(caplog):
    received = []
    consumer = MessageConsumer(on_any_message=lambda *args: received.append(args))

    def callback(key, body):
        raise ValueError("bad bulletin")

    await consumer._handle_message(callback, FakeMessage())

    assert "Failed handling message" in caplog.text
    assert "bad bulletin" in caplog.text
    assert received == []


# Stand-ins for aio-pika's connection, channel and queue that record what's asked of
# them, so start() and stop() can be checked without an AMQP server


@dataclass
class FakeQueue:
    name: str
    declare_kwargs: dict
    bindings: list = field(default_factory=list)
    consumers: list = field(default_factory=list)

    async def bind(self, exchange, routing_key=None):
        self.bindings.append((exchange, routing_key))

    async def consume(self, callback, no_ack=False):
        self.consumers.append((callback, no_ack))


class FakeChannel:
    def __init__(self):
        self.queues: list[FakeQueue] = []

    async def declare_queue(self, name, **kwargs):
        queue = FakeQueue(name, kwargs)
        self.queues.append(queue)
        return queue


class FakeCallbacks(list):
    def add(self, callback):
        self.append(callback)


class FakeConnection:
    def __init__(self):
        self.channel_ = FakeChannel()
        self.closed = False
        self.close_callbacks = FakeCallbacks()
        self.reconnect_callbacks = FakeCallbacks()

    async def channel(self):
        return self.channel_

    async def close(self):
        self.closed = True


@pytest.fixture
def connection(monkeypatch) -> FakeConnection:
    connection = FakeConnection()
    urls = []

    async def connect_robust(url):
        urls.append(url)
        return connection

    monkeypatch.setattr(message_consumer.aio_pika, "connect_robust", connect_robust)
    connection.urls = urls
    return connection


async def test_start_declares_binds_and_consumes_each_subscription(
    connection: FakeConnection, monkeypatch
):
    monkeypatch.setattr(message_consumer.config, "name", "tester")
    consumer = MessageConsumer()
    consumer.subscribe_to_topic("bulletins_WW", "v02.post.*.bulletins.*.WW.#", print)
    consumer.subscribe_to_topic("alerts", "v02.post.*.alerts.#", print)
    started = []

    await consumer.start(on_started=lambda: started.append(True))

    assert connection.urls == [MessageConsumer.CONNECTION_STR]
    queues = connection.channel_.queues
    assert [q.name for q in queues] == [
        "q_anonymous.eccc-msc-amqp-alerts.tester.bulletins_WW",
        "q_anonymous.eccc-msc-amqp-alerts.tester.alerts",
    ]
    assert all(q.declare_kwargs == {"auto_delete": True} for q in queues)
    assert [q.bindings for q in queues] == [
        [("xpublic", "v02.post.*.bulletins.*.WW.#")],
        [("xpublic", "v02.post.*.alerts.#")],
    ]
    assert all(len(q.consumers) == 1 and q.consumers[0][1] is True for q in queues)
    assert started == [True]


async def test_consumed_messages_reach_the_subscription_callback(
    connection: FakeConnection,
):
    calls = []
    consumer = MessageConsumer()
    consumer.subscribe_to_topic(
        "alerts", "v02.post.*.alerts.#", lambda *a: calls.append(a)
    )
    await consumer.start()

    on_message = connection.channel_.queues[0].consumers[0][0]
    await on_message(FakeMessage())

    assert calls == [(ROUTING_KEY, BODY)]


async def test_stop_closes_the_connection(connection: FakeConnection):
    consumer = MessageConsumer()
    await consumer.start()

    await consumer.stop()

    assert connection.closed


async def test_stop_before_start_does_nothing():
    await MessageConsumer().stop()


async def test_warns_when_connection_drops(connection: FakeConnection, caplog):
    consumer = MessageConsumer()
    await consumer.start()

    for callback in connection.close_callbacks:
        callback(connection, ConnectionResetError("network went away"))

    assert "AMQP connection lost" in caplog.text


async def test_no_connection_lost_warning_when_stopping(
    connection: FakeConnection, caplog
):
    consumer = MessageConsumer()
    await consumer.start()
    await consumer.stop()

    # What aio-pika does when we close the connection ourselves
    for callback in connection.close_callbacks:
        callback(connection, asyncio.CancelledError())

    assert "AMQP connection lost" not in caplog.text
