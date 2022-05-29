# eccc-msc-amqp-alerts
# Copyright (C) 2022  Justin A. S. Bull
# See __init__.py for full notice

import typing as t

import pika.spec
from pika.adapters.blocking_connection import BlockingChannel

OnMessageCallback = t.Callable[
    [BlockingChannel, pika.spec.Basic.Deliver, pika.spec.BasicProperties, bytes],
    None,
]
