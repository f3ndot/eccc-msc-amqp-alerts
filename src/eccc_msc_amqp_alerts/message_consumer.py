# eccc-msc-amqp-alerts
# Copyright (C) 2026  Justin A. S. Bull
# See __init__.py for full notice

import functools
import inspect
import logging
import typing as t
from collections import defaultdict
from dataclasses import dataclass

import aio_pika
from aio_pika.abc import AbstractIncomingMessage, AbstractRobustConnection

from .config import config
from .types import OnAnyMessageCallable, OnMessageCallback

logger = logging.getLogger(__name__)


class TopicStatistics:
    def __init__(self) -> None:
        self.routing_keys: defaultdict[str, int] = defaultdict(int)

    def __str__(self) -> str:
        s = [
            "Most popular topics:",
            "====================",
        ]
        singles_count = 0
        for k, v in sorted(
            self.routing_keys.items(), key=lambda pair: pair[1], reverse=True
        ):
            if v == 1:
                singles_count += 1
                # stop a long tail. consider truncating by subtopic depth instead?
                if singles_count > 10:
                    s.append("...")
                    break
            s.append("{:<70} {}".format(k, v))
        return "\n".join(s)

    def log_statistics(self):
        for line in str(self).split("\n"):
            logger.info(line)


@dataclass
class Subscription:
    """A queue to declare, bind to the exchange and consume from once connected"""

    name: str
    routing_key: str
    callback: OnMessageCallback


class MessageConsumer:
    CONNECTION_STR = "amqps://anonymous:anonymous@dd.weather.gc.ca:5671"
    EXCHANGE = "xpublic"

    def __init__(
        self,
        on_any_message: t.Optional[OnAnyMessageCallable] = None,
        url: str = CONNECTION_STR,
    ) -> None:
        self.stats = TopicStatistics()
        self.on_any_message = on_any_message
        self._url = url
        self._subscriptions: list[Subscription] = []
        self._connection: AbstractRobustConnection | None = None
        self._stopping = False

    def subscribe_to_topic(
        self,
        name: str,
        routing_key: str,
        callback: OnMessageCallback,
    ) -> Subscription:
        """Call before `start()`"""
        subscription = Subscription(name, routing_key, callback)
        self._subscriptions.append(subscription)
        return subscription

    async def start(self, on_started: t.Optional[t.Callable[[], t.Any]] = None):
        """Connects, then declares, binds and consumes a queue for each subscription.
        Returns once consuming; messages are then handled in the background.

        The connection is robust: if it drops, aio-pika keeps reconnecting and restores
        the queues, bindings and consumers. Only the very first connection attempt
        raises if it fails."""
        logger.info(f"Connecting to {self._url}...")
        connection = await aio_pika.connect_robust(self._url)
        self._connection = connection
        connection.close_callbacks.add(self._on_connection_lost)
        connection.reconnect_callbacks.add(self._on_reconnected)
        channel = await connection.channel()
        for subscription in self._subscriptions:
            queue_name = self._queue_name(subscription.name)
            logger.info(f"Declaring queue {queue_name}")
            # Deleted by the server once we stop consuming, so nothing is left behind
            queue = await channel.declare_queue(queue_name, auto_delete=True)
            logger.info(
                f"Binding {self.EXCHANGE} to {queue_name} with {subscription.routing_key}"
            )
            await queue.bind(self.EXCHANGE, routing_key=subscription.routing_key)
            await queue.consume(
                functools.partial(self._handle_message, subscription.callback),
                no_ack=True,  # let's keep it simple
            )
        logger.info(f"Consuming from {len(self._subscriptions)} queues")
        if on_started:
            on_started()

    async def stop(self):
        """Closes the connection, which stops consuming. The server then deletes our
        queues."""
        if self._connection is not None:
            logger.info("Closing AMQP connection")
            self._stopping = True
            await self._connection.close()
            self._connection = None
            logger.info("AMQP connection closed")

    def _on_connection_lost(self, _connection, exc: BaseException | None = None):
        # aio-pika calls this when we close the connection ourselves too
        if exc is not None and not self._stopping:
            logger.warning(f"AMQP connection lost, reconnecting: {exc!r}")

    def _on_reconnected(self, _connection):
        logger.warning("AMQP connection re-established, consuming again")

    def _queue_name(self, subname: str) -> str:
        return f"q_anonymous.eccc-msc-amqp-alerts.{config.name}.{subname}"

    async def _handle_message(
        self, callback: OnMessageCallback, message: AbstractIncomingMessage
    ):
        """aio-pika runs this as its own task for each message, so a slow callback (eg.
        fetching bulletin text) doesn't hold up the messages behind it. Messages can
        therefore finish out of order."""
        routing_key = message.routing_key or ""
        self.stats.routing_keys[routing_key] += 1
        try:
            ret = callback(routing_key, message.body)
            if inspect.isawaitable(ret):
                ret = await ret
            if self.on_any_message:
                logger.info(
                    f"Calling on_any_message: {self.on_any_message} with {(routing_key, message.body, 'ret...')}"
                )
                self.on_any_message(routing_key, message.body, ret)
        except Exception:
            logger.exception(f"Failed handling message {routing_key}: {message.body!r}")
