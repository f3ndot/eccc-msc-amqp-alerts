# eccc-msc-amqp-alerts
# Copyright (C) 2022  Justin A. S. Bull
# See __init__.py for full notice

from asyncio import AbstractEventLoop
import asyncio
import typing as t
import logging
import functools
import pika
import pika.spec
from pika.exchange_type import ExchangeType
from pika.adapters.asyncio_connection import AsyncioConnection
from dataclasses import dataclass
from collections import defaultdict

from .config import config
from .types import OnAnyMessageCallable, OnMessageCallback

if t.TYPE_CHECKING:
    import pika.frame
    import pika.channel

logger = logging.getLogger(__name__)


class TopicStatistics:
    routing_keys: defaultdict[str, int] = defaultdict(int)

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
class Queue:
    """Keeps track of queues created/declared and bound"""

    name: str
    exchange: str
    routing_key: str
    callback: OnMessageCallback
    channel: "pika.channel.Channel"
    consumer_tag: t.Optional[str] = None

    consuming = False
    deleted = False
    was_consuming = False
    bound = False


class MessageConsumer:
    CONNECTION_STR = "amqps://anonymous:anonymous@dd.weather.gc.ca:5671"
    EXCHANGE = "xpublic"
    EXCHANGE_TYPE = ExchangeType.topic

    def __init__(self, on_any_message: t.Optional[OnAnyMessageCallable] = None) -> None:
        self.should_reconnect = False
        self.was_consuming = False

        self.stats = TopicStatistics()

        self._connection: AsyncioConnection = None
        self._channel: "pika.channel.Channel" = None
        self._closing = False
        self._on_started_cb_fired = False

        self.on_any_message = on_any_message

        self._queues: list[Queue] = []

        self._url = self.CONNECTION_STR
        # In production, experiment with higher prefetch values
        # for higher consumer throughput
        self._prefetch_count = 1
        # logger.info(f"Connecting to {self._connection_string}...")
        # self.connection = pika.BlockingConnection(
        #     pika.URLParameters(self._connection_string)
        # )
        # logger.info("Creating channel...")
        # self.channel = self.connection.channel()

    def _consuming(self):
        return any([q.consuming for q in self._queues])

    def connect(self, loop: t.Optional[AbstractEventLoop] = None) -> AsyncioConnection:
        """This method connects to RabbitMQ, returning the connection handle. When the
        connection is established, the `on_connection_open` method will be invoked by
        pika.
        """
        logger.info(f"Connecting to {self._url}...")
        return AsyncioConnection(
            parameters=pika.URLParameters(self._url),
            on_open_callback=self.on_connection_open,
            on_open_error_callback=self.on_connection_open_error,
            on_close_callback=self.on_connection_closed,
            custom_ioloop=loop,
        )

    def close_connection(self):
        for queue in self._queues:
            queue.consuming = False
        if self._connection.is_closing or self._connection.is_closed:
            logger.info("Connection is closing or already closed")
        else:
            logger.info("Closing connection")
            self._connection.close()

    def on_connection_open(self, _unused_connection: AsyncioConnection):
        """This method is called by pika once the connection to RabbitMQ has been
        established. It passes the handle to the connection object in case we need it,
        but in this case, we'll just mark it unused.
        """
        logger.info("Connection opened")
        self.open_channel()

    def on_connection_open_error(
        self, _unused_connection: AsyncioConnection, err: Exception
    ):
        """This method is called by pika if the connection to RabbitMQ can't be
        established.
        """
        logger.error("Connection open failed: %s", err)
        self.reconnect()

    def on_connection_closed(
        self, _unused_connection: AsyncioConnection, reason: Exception
    ):
        """This method is invoked by pika when the connection to RabbitMQ is closed
        unexpectedly. Since it is unexpected, we will reconnect to RabbitMQ if it
        disconnects.
        """
        self._channel = None
        if self._closing:
            # NOTE: This isn't threadsafe. See `IOLoop.stop`'s docblock
            # TODO: Disable if externally provided ioloop
            # self._connection.ioloop.stop()
            pass
        else:
            logger.warning("Connection closed, reconnect necessary: %s", reason)
            self.reconnect()

    def reconnect(self):
        """Will be invoked if the connection can't be opened or is closed. Indicates
        that a reconnect is necessary then stops the ioloop.
        """
        self.should_reconnect = True
        self.stop()

    def open_channel(self):
        """Open a new channel with RabbitMQ by issuing the Channel.Open RPC command.
        When RabbitMQ responds that the channel is open, the `on_channel_open` callback
        will be invoked by pika.
        """
        logger.info("Creating a new channel")
        self._connection.channel(on_open_callback=self.on_channel_open)

    def on_channel_open(self, channel: "pika.channel.Channel"):
        """This method is invoked by pika when the channel has been opened. The channel
        object is passed in so we can make use of it. Since the channel is now open,
        we'll declare the exchange to use.
        """
        logger.info("Channel opened")
        self._channel = channel
        self.add_on_channel_close_callback()

        # Got a remote Channel.Close command from MSC with this message:
        #     "ACCESS_REFUSED - access to exchange 'xpublic' in vhost '/' refused for user 'anonymous'"
        # Seems like we can't declare exchanges :shrug:
        # So instead we jump straight into declaring queues
        # self.setup_exchange(self.EXCHANGE)
        self.setup_queues()

    def add_on_channel_close_callback(self):
        """This method tells pika to call the `on_channel_closed` method if RabbitMQ
        unexpectedly closes the channel.
        """
        logger.info("Adding channel close callback")
        self._channel.add_on_close_callback(self.on_channel_closed)

    def on_channel_closed(self, channel: "pika.channel.Channel", reason: Exception):
        """Invoked by pika when RabbitMQ unexpectedly closes the channel. Channels are
        usually closed if you attempt to do something that violates the protocol, such
        as re-declare an exchange or queue with different parameters. In this case,
        we'll close the connection to shutdown the object.
        """
        logger.warning("Channel %i was closed: %s", channel, reason)
        self.close_connection()

    def setup_exchange(self, exchange_name: str):
        """Setup the exchange on RabbitMQ by invoking the Exchange.Declare RPC command.
        When it is complete, the `on_exchange_declareok` method will be invoked by pika.
        """
        logger.info("Declaring exchange: %s", exchange_name)
        # Note: using functools.partial is not required, it is demonstrating
        # how arbitrary data can be passed to the callback when it is called
        cb = functools.partial(self.on_exchange_declareok, userdata=exchange_name)
        self._channel.exchange_declare(
            exchange=exchange_name, exchange_type=self.EXCHANGE_TYPE, callback=cb
        )

    def on_exchange_declareok(self, _unused_frame: "pika.frame.Method", userdata: str):
        """Invoked by pika when RabbitMQ has finished the Exchange.Declare RPC
        command.
        """
        logger.info("Exchange declared: %s", userdata)
        self.setup_queues()

    def setup_queues(self):
        """Setup the queues on RabbitMQ by invoking the Queue.Declare RPC command for
        each queue we wish to listen to a particular topic on. When each one completes,
        the `on_queue_declareok` method will be invoked by pika.
        """
        for queue in self._queues:
            logger.info(f"Declaring queue {queue.name}")
            cb = functools.partial(self.on_queue_declareok, userdata=queue)
            # self._channel.queue_declare(queue=queue.name, callback=cb)
            self._channel.queue_declare(queue=queue.name, callback=cb, auto_delete=True)

    def on_queue_declareok(self, _unused_frame: "pika.frame.Method", userdata: Queue):
        """Method invoked by pika when the Queue.Declare RPC call made in
        setup_queue has completed. In this method we will bind the queue
        and exchange together with the routing key by issuing the Queue.Bind
        RPC command. When this command is complete, the on_bindok method will
        be invoked by pika.
        :param pika.frame.Method _unused_frame: The Queue.DeclareOk frame
        :param str|unicode userdata: Extra user data (queue name)
        """
        queue = userdata
        logger.info(f"Binding {self.EXCHANGE} to {queue.name} with {queue.routing_key}")
        cb = functools.partial(self.on_bindok, userdata=queue)
        self._channel.queue_bind(
            queue.name, self.EXCHANGE, routing_key=queue.routing_key, callback=cb
        )

    def on_bindok(self, _unused_frame: "pika.frame.Method", userdata: Queue):
        """Invoked by pika when the Queue.Bind method has completed."""
        logger.info("Queue bound: %s", userdata.name)
        userdata.bound = True
        # NOTE: See other leaky note at `on_cancelok``
        if all([q.bound for q in self._queues]):
            self.start_consuming()
            # self.set_qos()

    # def set_qos(self):
    #     """This method sets up the consumer prefetch to only be delivered
    #     one message at a time. The consumer must acknowledge this message
    #     before RabbitMQ will deliver another one. You should experiment
    #     with different prefetch values to achieve desired performance.
    #     """
    #     self._channel.basic_qos(
    #         prefetch_count=self._prefetch_count, callback=self.on_basic_qos_ok)

    # def on_basic_qos_ok(self, _unused_frame):
    #     """Invoked by pika when the Basic.QoS method has completed. At this
    #     point we will start consuming messages by calling start_consuming
    #     which will invoke the needed RPC commands to start the process.
    #     :param pika.frame.Method _unused_frame: The Basic.QosOk response frame
    #     """
    #     LOGGER.info('QOS set to: %d', self._prefetch_count)
    #     self.start_consuming()

    def start_consuming(self):
        """This method sets up the consumer by first calling `add_on_cancel_callback`
        so that the object is notified if RabbitMQ cancels the consumer. It then issues
        the Basic.Consume RPC command which returns the consumer tag that is used to
        uniquely identify the consumer with RabbitMQ. We keep the value to use it when
        we want to cancel consuming. The `on_message` method is passed in as a callback
        pika will invoke when a message is fully received.
        """
        logger.info("Issuing consumer related RPC commands")
        self.add_on_cancel_callback()
        for queue in self._queues:
            queue.consumer_tag = self._channel.basic_consume(
                queue.name,
                on_message_callback=self._wrap_callback(queue.callback),
                auto_ack=True,  # let's keep it simple
                callback=self.on_consumeok,
            )
            queue.consuming = True
            queue.was_consuming = True
            logger.info(f"Consumer tag for {queue.name} is {queue.consumer_tag}")

    def on_consumeok(self, _unused_frame: "pika.frame.Method"):
        if not self._on_started_cb:
            return
        if self._on_started_cb_fired:
            return

        if all([q.consuming for q in self._queues]):
            logger.info(f"Firing _on_started_cb callback! {self._on_started_cb}")
            self._on_started_cb_fired = True
            self._on_started_cb()
        else:
            consuming_queues_count = len([q for q in self._queues if q.consuming])
            logger.info(
                f"Waiting for {consuming_queues_count} queues to start consuming..."
            )

    def add_on_cancel_callback(self):
        """Add a callback that will be invoked if RabbitMQ cancels the consumer for some
        reason. If RabbitMQ does cancel the consumer, `on_consumer_cancelled` will be
        invoked by pika.
        """
        logger.info("Adding consumer cancellation callback")
        self._channel.add_on_cancel_callback(self.on_consumer_cancelled)

    def on_consumer_cancelled(self, method_frame: "pika.frame.Method"):
        """Invoked by pika when RabbitMQ sends a Basic.Cancel for a consumer receiving
        messages.
        """
        logger.info("Consumer was cancelled remotely, shutting down: %r", method_frame)
        if self._channel:
            self._channel.close()

    def stop_consuming(self):
        """Tell RabbitMQ that you would like to stop consuming by sending the
        Basic.Cancel RPC command.
        """
        if self._channel:
            logger.info("Sending a Basic.Cancel RPC command to RabbitMQ")
            for queue in self._queues:
                cb = functools.partial(self.on_cancelok, userdata=queue)
                self._channel.basic_cancel(queue.consumer_tag, cb)

    def on_cancelok(self, _unused_frame: "pika.frame.Method", userdata: Queue):
        """This method is invoked by pika when RabbitMQ acknowledges the cancellation of
        a consumer. At this point we will close the channel. This will invoke the
        `on_channel_closed` method once the channel has been closed, which will in-turn
        close the connection.
        :param pika.frame.Method _unused_frame: The Basic.CancelOk frame
        :param str|unicode userdata: Extra user data (consumer tag)
        """
        queue = userdata
        queue.bound = False  # I assume a cancelled queue is one that's already unbound
        queue.consuming = False
        logger.info(
            "RabbitMQ acknowledged the cancellation of the consumer: %s",
            queue.consumer_tag,
        )

        if not self._consuming():
            for q in self._queues:
                q.deleted = True
            self.close_channel()
        else:
            consuming_queues_count = len([q for q in self._queues if q.consuming])
            logger.info(
                f"Waiting for {consuming_queues_count} queues to stop consuming..."
            )
        # No need to do below because auto_delete=True
        # cb = functools.partial(self.on_deleteok, userdata=queue)
        # self._channel.queue_delete(queue=queue.name, callback=cb)

    def on_deleteok(self, _unused_frame: "pika.frame.Method", userdata: Queue):
        queue = userdata
        queue.deleted = True

        # NOTE: With the queues representing the source of truth of consuming state,
        # this could leak/channel never closes if one of them fails to cancel. Should
        # probably inverse the relationship where this class has the _consuming variable
        # and the individual queues respond to that reality
        all_queues_stopped_consuming = not self._consuming()
        all_queues_deleted = all([q.deleted for q in self._queues])

        if all_queues_stopped_consuming and all_queues_deleted:
            logger.info("All queues stopped and deleted, closing channel")
            logger.info("!!!!!!!!!!!!!!! CLOSING CHANNEL !!!!!!!!!!!!!!!!!!!!!")
            self.close_channel()
        else:
            # Double NOTE: multiple list comprehensions here can race
            consuming_queues_count = len([q for q in self._queues if q.consuming])
            active_queues_count = len([q for q in self._queues if not q.deleted])
            logger.info(
                f"Waiting to delete {active_queues_count} queues and "
                f"{consuming_queues_count} queues to stop consuming..."
            )

    def close_channel(self):
        """Call to close the channel with RabbitMQ cleanly by issuing the Channel.Close
        RPC command.
        """
        logger.info("Closing the channel")
        self._channel.close()

    def run(
        self,
        on_started: t.Optional[t.Callable] = None,
        loop: t.Optional[AbstractEventLoop] = None,
    ):
        """Run the example consumer by connecting to RabbitMQ and then starting the
        IOLoop to block and allow the AsyncioConnection to operate.
        """
        self._on_started_cb = on_started
        self._connection = self.connect(loop=loop)
        if loop is None:
            self._connection.ioloop.run_forever()

    def stop(self):
        """Cleanly shutdown the connection to RabbitMQ by stopping the consumer with
        RabbitMQ. When RabbitMQ confirms the cancellation, `on_cancelok` will be invoked
        by pika, which will then closing the channel and connection. The IOLoop is
        started again because this method is invoked when CTRL-C is pressed raising a
        KeyboardInterrupt exception. This exception stops the IOLoop which needs to be
        running for pika to communicate with RabbitMQ. All of the commands issued prior
        to starting the IOLoop will be buffered but not processed.
        """
        if not self._closing:
            self._closing = True
            logger.info("Stopping")
            if self._consuming():
                self.stop_consuming()
                # TODO: guard this if `run()` was passed in a `loop` arg
                # self._connection.ioloop.run_forever()
            else:
                self._connection.ioloop.stop()
            logger.info("Stopped")

    def _get_con_state(self):
        return self._connection._STATE_NAMES[self._connection.connection_state]

    async def _log_con_state_forever(self, every=1):
        while True:
            logger.info(
                f"Waiting for AMQP shutdown... Connection state: {self._get_con_state()}"
            )
            await asyncio.sleep(0.5)

    async def _stop_and_wait(self):
        _previous_state = self._get_con_state()
        self.stop()
        task = asyncio.create_task(self._log_con_state_forever())
        while True:
            _current_state = self._get_con_state()
            if _previous_state != _current_state:
                _previous_state = self._get_con_state()
                logger.info(
                    f"Waiting for AMQP shutdown... New connection state: {self._get_con_state()}"
                )
            await asyncio.sleep(0)
            if self._connection.is_closed:
                logger.info(f"AMQP SHUT DOWN! Connection is {self._get_con_state()}")
                task.cancel()
                return True

    async def stop_and_wait(self, timeout: float):
        await asyncio.wait_for(self._stop_and_wait(), timeout=timeout)

    def subscribe_to_topic(
        self,
        name: str,
        routing_key: str,
        callback: OnMessageCallback,
    ):
        queue_name = self._queue_name(name)
        queue = Queue(
            name=queue_name,
            exchange=self.EXCHANGE,
            routing_key=routing_key,
            callback=callback,
            channel=self._channel,
        )
        self._queues.append(queue)
        return queue

    def _queue_name(self, subname):
        return f"q_anonymous.eccc-msc-amqp-alerts.{config.name}.{subname}"

    def _wrap_callback(self, func: OnMessageCallback):
        """Returns a function/callable that wraps the underlying callback function, so
        it can collect some statistics"""

        def wraps(
            channel: "pika.channel.Channel",
            method: pika.spec.Basic.Deliver,
            properties: pika.spec.BasicProperties,
            body: bytes,
        ):
            routing_key: str = method.routing_key
            self.stats.routing_keys[routing_key] += 1
            ret = func(channel, method, properties, body)
            if self.on_any_message:
                logger.info(
                    f"Calling on_any_message: {self.on_any_message} with {(routing_key, body, 'ret...')}"
                )
                self.on_any_message(routing_key, body, ret)

        return wraps
