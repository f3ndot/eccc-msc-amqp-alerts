import asyncio

import pika.spec

from eccc_msc_amqp_alerts.message_consumer import MessageConsumer

ROUTING_KEY = "v02.post.20261031.WXO-DD.bulletins.alphanumeric.20261031.SA.CYXC.15"
BODY = b"20261031151613.417 https://dd.weather.gc.ca/ some/path"


async def wait_until(condition, timeout: float = 2):
    """Lets callbacks that run as background tasks finish before asserting"""
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.01)


async def test_passes_callback_result_to_on_any_message():
    received = []
    consumer = MessageConsumer(on_any_message=lambda *args: received.append(args))
    handle = consumer._wrap_callback(lambda channel, method, props, body: "bulletin")

    handle(None, pika.spec.Basic.Deliver(routing_key=ROUTING_KEY), None, BODY)

    await wait_until(lambda: received)
    assert received == [(ROUTING_KEY, BODY, "bulletin")]


async def test_counts_messages_per_routing_key():
    consumer = MessageConsumer()
    handle = consumer._wrap_callback(lambda channel, method, props, body: None)

    for _ in range(3):
        handle(None, pika.spec.Basic.Deliver(routing_key=ROUTING_KEY), None, BODY)

    assert consumer.stats.routing_keys[ROUTING_KEY] == 3


async def test_awaits_async_callbacks_before_on_any_message():
    received = []
    consumer = MessageConsumer(on_any_message=lambda *args: received.append(args))

    async def callback(channel, method, props, body):
        await asyncio.sleep(0.01)
        return "fetched bulletin"

    handle = consumer._wrap_callback(callback)
    handle(None, pika.spec.Basic.Deliver(routing_key=ROUTING_KEY), None, BODY)

    await wait_until(lambda: received)
    assert received == [(ROUTING_KEY, BODY, "fetched bulletin")]


async def test_logs_callback_errors_instead_of_raising(caplog):
    received = []
    consumer = MessageConsumer(on_any_message=lambda *args: received.append(args))

    def callback(channel, method, props, body):
        raise ValueError("bad bulletin")

    handle = consumer._wrap_callback(callback)
    handle(None, pika.spec.Basic.Deliver(routing_key=ROUTING_KEY), None, BODY)

    await wait_until(lambda: "Failed handling message" in caplog.text)
    assert "bad bulletin" in caplog.text
    assert received == []
