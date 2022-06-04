# eccc-msc-amqp-alerts
# Copyright (C) 2022  Justin A. S. Bull
# See __init__.py for full notice

# TODO: can some of these be "if t.TYPE_CHECKING"?
import typing as t
import asyncio
import pika.spec
from pika.adapters.blocking_connection import BlockingChannel

OnMessageCallback = t.Callable[
    [BlockingChannel, pika.spec.Basic.Deliver, pika.spec.BasicProperties, bytes],
    t.Any,
]


class OnAnyMessageCallable(t.Protocol):
    def __call__(self, routing_key: str, body: bytes, ret: t.Any) -> None:
        ...


OnMessageAIOQueue = asyncio.Queue[tuple[str, bytes, t.Any]]
