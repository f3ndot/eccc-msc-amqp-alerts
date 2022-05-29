import typing as t

import pika.spec
from pika.adapters.blocking_connection import BlockingChannel

OnMessageCallback = t.Callable[
    [BlockingChannel, pika.spec.Basic.Deliver, pika.spec.BasicProperties, bytes],
    None,
]
