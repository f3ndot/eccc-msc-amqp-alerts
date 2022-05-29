# eccc-msc-amqp-alerts
# Copyright (C) 2022  Justin A. S. Bull
# See __init__.py for full notice

from dataclasses import dataclass
import typing as t
import pika
import pika.spec
from collections import defaultdict
from pika.exceptions import StreamLostError

from .config import config
from .types import OnMessageCallback

if t.TYPE_CHECKING:
    import pika.frame
    from pika.adapters.blocking_connection import BlockingChannel


class TopicStatistics:
    routing_keys: defaultdict[str, int] = defaultdict(int)

    def print_statistics(self):
        print("Most popular topics:")
        print("====================")
        singles_count = 0
        for k, v in sorted(
            self.routing_keys.items(), key=lambda pair: pair[1], reverse=True
        ):
            if v == 1:
                singles_count += 1
                # stop a long tail. consider truncating by subtopic depth instead?
                if singles_count > 10:
                    print("...")
                    break
            print("{:<70} {:<100}".format(k, v))


@dataclass
class Queue:
    """Keeps track of queues created/declared and bound"""

    name: str
    exchange: str
    routing_key: str
    callback: OnMessageCallback
    channel: "BlockingChannel"
    consumer_tag: t.Optional[str] = None

    def declare(self):
        declare_result: "pika.frame.Method" = self.channel.queue_declare(
            queue=self.name,
            auto_delete=True,  # let's keep it simple
            durable=False,
        )
        if not isinstance(declare_result.method, pika.spec.Queue.DeclareOk):
            raise RuntimeError("Unable to declare queue")
        return declare_result

    def bind(self):
        bind_result: "pika.frame.Method" = self.channel.queue_bind(
            queue=self.name,
            exchange=self.exchange,
            routing_key=self.routing_key,
        )
        if not isinstance(bind_result.method, pika.spec.Queue.BindOk):
            raise RuntimeError("Unable to bind queue")
        return bind_result


class MessageConsumer:
    _connection_string = "amqps://anonymous:anonymous@dd.weather.gc.ca:5671"
    _exchange = "xpublic"

    connection: pika.BlockingConnection
    channel: "BlockingChannel"
    queues: list[Queue] = []
    stats = TopicStatistics()
    _shutting_down = False

    def __init__(self) -> None:
        print(f"[*] Connecting to {self._connection_string}...")
        self.connection = pika.BlockingConnection(
            pika.URLParameters(self._connection_string)
        )
        print("[*] Creating channel...")
        self.channel = self.connection.channel()

    def subscribe_to_topic(
        self,
        name: str,
        routing_key: str,
        callback: OnMessageCallback,
    ):
        # TODO: dont assume state of channel(s) and connection, their declarations or bindings
        queue_name = self._queue_name(name)
        queue = Queue(
            name=queue_name,
            exchange=self._exchange,
            routing_key=routing_key,
            callback=callback,
            channel=self.channel,
        )
        self.queues.append(queue)
        return queue

    def consume(self):
        # TODO: validate this approach. research this: https://pika.readthedocs.io/en/stable/examples/blocking_consume_recover_multiple_hosts.html
        for queue in self.queues:
            queue.declare()
            queue.bind()
            queue.consumer_tag = self.channel.basic_consume(
                queue=queue.name,
                on_message_callback=self._wrap_callback(queue.callback),
                auto_ack=True,  # let's keep it simple
            )
            print(f"[*] Consumer tag for {queue.name} is {queue.consumer_tag}")
        try:
            self.channel.start_consuming()
        except StreamLostError as e:
            print(f"[!] Damn! Encountered StreamLostError: {repr(e)}")
        except KeyboardInterrupt:
            print("[!] You pressed Ctrl+C or triggered SIGINT!")
        finally:
            self.shutdown()

    def shutdown(self):
        if self._shutting_down is True:
            return
        self._shutting_down = True
        print("[*] Shutting down... ", end="", flush=True)

        # since queues auto-delete, this should be enough?
        self.channel.stop_consuming()
        print(" Stopped consumer(s)...", end="", flush=True)

        for queue in self.queues:
            queue.consumer_tag = None
        # for queue in self.queues:
        #     # TODO: more gracefully handle this situation
        #     if self.channel.is_closed:
        #         break
        #     unbind_result = self.channel.queue_unbind(
        #         queue=queue.name,
        #         exchange=queue.exchange,
        #         routing_key=queue.routing_key,
        #     )
        #     if not isinstance(unbind_result.method, pika.spec.Queue.UnbindOk):
        #         print("[!] Unable to unbind queue. Proceeding anyway...")
        #     delete_result = self.channel.queue_delete(queue=queue.name)
        #     if not isinstance(delete_result.method, pika.spec.Queue.DeleteOk):
        #         print("[!] Unable to delete queue. Proceeding anyway...")
        #     print(f"[.] Shut down {queue.name}")
        # self.queues.clear()
        if self.channel.is_open:
            self.channel.close()
            print(" Closed channel...", end="", flush=True)
        if self.connection.is_open:
            self.connection.close()
            print(" Closed connection...", end="", flush=True)
        print("")
        self.stats.print_statistics()
        self._shutting_down = False

    def _queue_name(self, subname):
        return f"q_anonymous.eccc-msc-amqp-alerts.{config.name}.{subname}"

    def _wrap_callback(self, func: OnMessageCallback):
        """Returns a function/callable that wraps the underlying callback function, so
        it can collect some statistics"""

        def wraps(
            channel: "BlockingChannel",
            method: pika.spec.Basic.Deliver,
            properties: pika.spec.BasicProperties,
            body: bytes,
        ):
            routing_key: str = method.routing_key
            self.stats.routing_keys[routing_key] += 1
            func(channel, method, properties, body)

        return wraps
