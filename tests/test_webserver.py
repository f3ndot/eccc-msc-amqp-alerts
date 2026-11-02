import asyncio
import json

import pytest

from eccc_msc_amqp_alerts import webserver
from eccc_msc_amqp_alerts.message_consumer import MessageConsumer
from eccc_msc_amqp_alerts.webserver import (
    AmqpBulletinMessage,
    ConsumerOrchestrator,
    WebsocketConnection,
)

ROUTING_KEY = "v02.post.20261101.WXO-DD.bulletins.alphanumeric.20261101.SA.CYXC.15"
BULLETIN = "SACN43 CYXC 011500\nMETAR CYXC 011500Z 27010KT 15SM FEW040 08/M02 A2992="


def body(header: str = "SACN43_CYXC_011500") -> bytes:
    return (
        "20261101151613.417 https://dd.weather.gc.ca/ "
        f"20261101/WXO-DD/bulletins/alphanumeric/20261101/SA/CYXC/15/{header}___12345"
    ).encode()


def message(header: str = "SACN43_CYXC_011500") -> AmqpBulletinMessage:
    return AmqpBulletinMessage(
        routing_key=ROUTING_KEY, message=body(header).decode(), bulletin=BULLETIN
    )


@pytest.fixture
def orc() -> ConsumerOrchestrator:
    return ConsumerOrchestrator(MessageConsumer())


def visitor(
    orc: ConsumerOrchestrator, maxsize=webserver.WEBSOCKET_QUEUE_SIZE, **config
):
    conn = WebsocketConnection(queue=asyncio.Queue(maxsize=maxsize))
    conn.config.update(config)
    orc.websockets[id(conn.queue)] = conn
    return conn


def drain(queue: asyncio.Queue) -> list:
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


def test_payload_is_the_message_as_json():
    payload = json.loads(message().payload)

    assert payload["routing_key"] == ROUTING_KEY
    assert payload["message"] == body().decode()
    assert payload["bulletin"] == BULLETIN
    assert payload["region"] == "CN"
    assert payload["decoded_wmo_header"]["centre"]
    # Serialized like Quart's send_json, which the page has always received
    assert payload["decoded_wmo_header"]["datetime"] == "Sun, 01 Nov 2026 15:00:00 GMT"


def test_payload_is_built_once_however_many_visitors(orc, monkeypatch):
    calls = 0
    real_decode = webserver.decode_wmo_header

    def counting_decode(header):
        nonlocal calls
        calls += 1
        return real_decode(header)

    monkeypatch.setattr(webserver, "decode_wmo_header", counting_decode)
    visitors = [visitor(orc, sigmet_filter=True) for _ in range(5)]

    orc.push_to_websocket_queue(ROUTING_KEY, body(), BULLETIN)
    payloads = [conn.queue.get_nowait().payload for conn in visitors]

    assert calls == 1
    # The very same string, not five equal copies
    assert all(p is payloads[0] for p in payloads)


def test_jsondict_does_not_change_the_message():
    msg = message()
    before = repr(msg)

    msg.jsondict()

    # It used to add its extra keys to the message's own fields
    assert repr(msg) == before
    assert "decoded_wmo_header" not in before


def test_every_visitor_gets_each_message(orc):
    visitors = [visitor(orc) for _ in range(3)]

    orc.push_to_websocket_queue(ROUTING_KEY, body("SACN43_CYXC_011500"), BULLETIN)
    orc.push_to_websocket_queue(ROUTING_KEY, body("SACN44_CYXC_011500"), BULLETIN)

    for conn in visitors:
        assert [m.wmo_header for m in drain(conn.queue)] == [
            "SACN43 CYXC 011500",
            "SACN44 CYXC 011500",
        ]


def test_slow_visitor_loses_oldest_messages_not_newest(orc):
    slow = visitor(orc, maxsize=2)
    fast = visitor(orc, maxsize=10)

    for i in range(4):
        orc.push_to_websocket_queue(ROUTING_KEY, body(f"SACN4{i}_CYXC_011500"), None)

    assert [m.wmo_header for m in drain(slow.queue)] == [
        "SACN42 CYXC 011500",
        "SACN43 CYXC 011500",
    ]
    assert len(drain(fast.queue)) == 4


def test_region_filter_still_applies(orc):
    canada = visitor(orc, region_filter="CN")
    us = visitor(orc, region_filter="US")

    orc.push_to_websocket_queue(ROUTING_KEY, body(), BULLETIN)

    assert len(drain(canada.queue)) == 1
    assert drain(us.queue) == []


def test_sigmet_filter_still_applies(orc):
    filtering = visitor(orc, sigmet_filter=True)
    everything = visitor(orc)

    # WS: SIGMET
    orc.push_to_websocket_queue(ROUTING_KEY, body("WSCN31_CWAO_011500"), BULLETIN)

    assert drain(filtering.queue) == []
    assert len(drain(everything.queue)) == 1
