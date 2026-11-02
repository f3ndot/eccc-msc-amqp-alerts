# eccc-msc-amqp-alerts
# Copyright (C) 2026  Justin A. S. Bull
# See __init__.py for full notice

# TODO: can some of these be "if t.TYPE_CHECKING"?
import asyncio
import typing as t

if t.TYPE_CHECKING:
    from .webserver import AmqpBulletinMessage

# Called with each message's routing key and body. May be async
OnMessageCallback = t.Callable[[str, bytes], t.Any]


class OnAnyMessageCallable(t.Protocol):
    def __call__(self, routing_key: str, body: bytes, ret: t.Any) -> None: ...


OnMessageAIOQueue = asyncio.Queue["AmqpBulletinMessage"]
