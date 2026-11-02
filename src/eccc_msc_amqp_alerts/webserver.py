# eccc-msc-amqp-alerts
# Copyright (C) 2026  Justin A. S. Bull
# See __init__.py for full notice

import asyncio
import dataclasses
import functools
import json
import logging
import os
import signal
from datetime import datetime

from quart import Quart, render_template, send_file, websocket
from quart.utils import MustReloadError, observe_changes, restart

from .listen import close_http_client, consumer
from .message_consumer import MessageConsumer
from .types import OnMessageAIOQueue
from .wmo_header import AIRMET_SIGMET_SUBTYPES
from .wmo_header import decode_header as decode_wmo_header

logger = logging.getLogger(__name__)


class QuartWithConsumerOrc(Quart):
    consumer_orc: "ConsumerOrchestrator"
    consumer_orc_task: asyncio.Task


app = QuartWithConsumerOrc(__name__)

# Set on Ctrl+C/SIGTERM. Hypercorn won't finish shutting down until every connection
# has closed, and websockets otherwise stay open forever, so they watch this and close
# themselves.
shutting_down = asyncio.Event()
# How long a graceful shutdown gets before the process exits regardless
FORCE_SHUTDOWN_AFTER_SECS = 10
# Messages waiting to go out to each visitor. A visitor that falls this far behind
# loses its oldest unsent messages rather than its newest
WEBSOCKET_QUEUE_SIZE = 100


# TODO: This should go into listen.py's on_bulletin_message and be the returned object
# Shared by every visitor it's sent to, so the derived properties are cached and
# computed once per message, not once per visitor
@dataclasses.dataclass(repr=False)
class AmqpBulletinMessage:
    routing_key: str
    message: str
    bulletin: str | None

    @functools.cached_property
    def region(self):
        # FIXME: doesn't work on alert CAP messages.. different URL format. Probably
        # because only Canadian CAPs come thru. Eg message:
        #   20220612164605.996 https://dd4.weather.gc.ca /alerts/cap/20220612/LAND/16/T_MBCN00_C_LAND_202206121643_1119167019.cap
        # Should probably parse CAP to determine 'region' or just assume CA.
        #
        # TODO: parse body into its components as defined by MSC Datamart's scheme
        return self.message.split(" ")[-1].split("/")[-1][2:4]

    @functools.cached_property
    def decoded_wmo_header(self):
        # FIXME: doesn't work on alert CAP messages.. different URL format
        try:
            return decode_wmo_header(self.wmo_header)
        except ValueError:
            return None

    @property
    def wmo_header(self):
        _, _, path = self.message.split(" ")
        return " ".join(path.split("/")[-1].replace("_", " ").split(" ")[0:3]).rstrip()

    @property
    def bulletin_len(self):
        return len(self.bulletin) if self.bulletin else "N/A"

    def __repr__(self) -> str:
        repr_fields = ", ".join(
            f"{f.name}={getattr(self, f.name)}"
            for f in dataclasses.fields(self)
            if f.name != "bulletin"
        )
        return (
            self.__class__.__qualname__
            + f"({repr_fields}, region={self.region}), bulletin_len={self.bulletin_len}"
        )

    def jsondict(self):
        return {
            **dataclasses.asdict(self),
            "region": self.region,
            "decoded_wmo_header": self.decoded_wmo_header,
        }

    @functools.cached_property
    def payload(self) -> str:
        """The JSON sent to visitors. Serialized the same way `send_json` would"""
        return app.json.dumps(self.jsondict())


@dataclasses.dataclass
class WebsocketConnection:
    queue: OnMessageAIOQueue
    config: dict = dataclasses.field(
        default_factory=lambda: {"region_filter": "any", "sigmet_filter": False}
    )


class ConsumerOrchestrator:
    def __init__(self, consumer: MessageConsumer) -> None:
        self.last_bulletin: AmqpBulletinMessage | None = None
        self.consumer = consumer
        self.consumer.on_any_message = self.push_to_websocket_queue
        self.websockets: dict[str, WebsocketConnection] = {}
        self.dump_queue: OnMessageAIOQueue = asyncio.Queue(maxsize=100)

    def push_to_websocket_queue(self, routing_key: str, body: bytes, ret):
        # TODO: differentiate between alerts and bulletins with this callback
        message = AmqpBulletinMessage(
            routing_key=routing_key, message=body.decode(), bulletin=ret
        )
        self.last_bulletin = message
        logger.info(f"push_to_websocket_queue called with {message}")
        # try:
        #     self.dump_queue.put_nowait(message)
        # except asyncio.QueueFull:
        #     logger.info(
        #         f"SKIPPING PUSH {message} to dump queue {self.dump_queue} (is full)"
        #     )
        for ws_conn in self.websockets.values():
            self._push_to_ws_queue(message=message, conn=ws_conn)

    def _push_to_ws_queue(
        self, message: AmqpBulletinMessage, conn: WebsocketConnection
    ):
        _filter = conn.config["region_filter"]
        if _filter != "any" and message.region != _filter:
            logger.info(
                f"Skipping push {message} due to region filter {_filter} on queue {id(conn.queue)}"
            )
            return
        if (
            conn.config["sigmet_filter"]
            and message.decoded_wmo_header is not None
            and message.decoded_wmo_header["data_type_sub"] in AIRMET_SIGMET_SUBTYPES
        ):
            logger.info(
                f"Skipping push {message} due to AIRMET/SIGMET filter on queue {id(conn.queue)}"
            )
            return
        if conn.queue.full():
            dropped = conn.queue.get_nowait()
            logger.warning(
                f"Dropping oldest unsent {dropped} for slow websocket queue {id(conn.queue)}"
            )
        conn.queue.put_nowait(message)

    async def run(self):
        print("🔌 Connecting... ", end="", flush=True)
        try:
            await self.consumer.start(
                on_started=lambda: print("OK! Now listening for messages... 👂")
            )
        except Exception:
            # Once connected, aio-pika reconnects by itself. Only the first attempt
            # can fail like this
            logger.exception("Unable to connect to AMQP. No messages will arrive!")


@app.before_serving
async def start_amqp_listening():
    logger.info("Starting AMQP listening alongside Quart")
    app.consumer_orc = ConsumerOrchestrator(consumer)
    # Connecting happens in the background so the webserver can start serving
    app.consumer_orc_task = asyncio.create_task(app.consumer_orc.run())


@app.after_serving
async def shutdown():
    max_wait_secs = 5
    logger.info(
        f"Gracefully stopping AMQP listening (waiting up to {max_wait_secs}s)..."
    )
    # Stop it still connecting, or waiting for room on the AMQP server
    app.consumer_orc_task.cancel()
    try:
        await asyncio.wait_for(app.consumer_orc.consumer.stop(), max_wait_secs)
        logger.info("Gracefully STOPPED AMQP listening!")
    except asyncio.TimeoutError:
        logger.info(f"TIMED OUT! Waited {max_wait_secs}s. Forcefully shutting down...")
    await close_http_client()


@app.route("/")
async def index():
    return await render_template("index.html")


@app.route("/current_queues")
async def current_queues():
    websocket_queues = {}
    for ws_conn in app.consumer_orc.websockets.values():
        websocket_queues[id(ws_conn.queue)] = {
            "config": ws_conn.config,
            "qsize": ws_conn.queue.qsize(),
        }
    return {
        "dump_queue": app.consumer_orc.dump_queue.qsize(),
        "websocket_queues": websocket_queues,
    }


@app.route("/dump")
async def dump():
    items = []
    try:
        while True:
            item = app.consumer_orc.dump_queue.get_nowait()
            items.append(item.jsondict())
    except asyncio.QueueEmpty:
        return {"items": items}


async def ws_keepalive():
    while True:
        await asyncio.sleep(45)
        logger.info("Sending WS heartbeat...")
        await websocket.send(json.dumps({"heartbeat": str(datetime.now())}))


async def handle_recv_ws(conn: WebsocketConnection):
    while True:
        data = await websocket.receive_json()
        if "region_filter" in data:
            conn.config["region_filter"] = data["region_filter"]
            await websocket.send_json(
                {
                    "sysmsg": f"Changed to region filter to {data['region_filter']}",
                    "region_filter": data["region_filter"],
                }
            )
        if "sigmet_filter" in data:
            conn.config["sigmet_filter"] = data["sigmet_filter"]
            await websocket.send_json(
                {
                    "sysmsg": f"{'Ignoring' if data['sigmet_filter'] else 'Including'} SIGMET & AIRMET bulletins",
                    "sigmet_filter": data["sigmet_filter"],
                }
            )


async def send_from_queue(queue: OnMessageAIOQueue):
    while True:
        item = await queue.get()
        await websocket.send(item.payload)


@app.websocket("/ws")
async def ws():
    tasks: list[asyncio.Task] = []
    queue: OnMessageAIOQueue = asyncio.Queue(maxsize=WEBSOCKET_QUEUE_SIZE)
    conn = WebsocketConnection(queue=queue)
    try:
        logger.info(f"Adding {queue}")
        app.consumer_orc.websockets[id(queue)] = conn
        # await consumer_orc.send_websocket_from_queue_get(queue)
        await websocket.send_json(
            {
                "sysmsg": "Hello from websocket server! Queue provisioned, awaiting messages from live feed"
            }
        )
        tasks.append(asyncio.create_task(ws_keepalive()))
        tasks.append(asyncio.create_task(handle_recv_ws(conn)))
        if app.consumer_orc.last_bulletin is not None:
            await websocket.send_json(
                {"sysmsg": "Loading last received bulletin while you wait :-)"}
            )
            await websocket.send(app.consumer_orc.last_bulletin.payload)
        send_task = asyncio.create_task(send_from_queue(queue))
        shutdown_task = asyncio.create_task(shutting_down.wait())
        tasks += [send_task, shutdown_task]
        await asyncio.wait(
            [send_task, shutdown_task], return_when=asyncio.FIRST_COMPLETED
        )
        if send_task.done():
            # Surface whatever ended the send loop, eg. the client going away
            send_task.result()
        else:
            await websocket.send_json({"sysmsg": "Server is shutting down. Goodbye!"})
    finally:
        logger.info("stopping ws keepalive")
        for task in tasks:
            task.cancel()
        logger.info(f"Removing {queue}")
        del app.consumer_orc.websockets[id(queue)]


def _force_exit(reason: str):
    print(f"💥 {reason}. Forcing shutdown!", flush=True)
    os._exit(1)


async def _serve(host: str, port: int, debug: bool) -> bool:
    """Returns True if the server stopped so it could reload changed code"""
    loop = asyncio.get_running_loop()

    def begin_shutdown(reason: str):
        print(f"🛎️ {reason}", flush=True)
        shutting_down.set()
        loop.call_later(
            FORCE_SHUTDOWN_AFTER_SECS,
            _force_exit,
            f"Still running after {FORCE_SHUTDOWN_AFTER_SECS}s",
        )

    def on_signal():
        if shutting_down.is_set():
            _force_exit("Received second interrupt")
        begin_shutdown("Shutting down gracefully... Ctrl+C again to force")

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, on_signal)

    async def wait_for_shutdown() -> None:
        await shutting_down.wait()

    server = asyncio.create_task(
        app.run_task(
            host=host, port=port, debug=debug, shutdown_trigger=wait_for_shutdown
        )
    )
    reload = False
    if debug:
        # Watches the source of every loaded module, raising when one changes. Ends
        # quietly if we shut down for some other reason first
        try:
            await observe_changes(asyncio.sleep, shutting_down)
        except MustReloadError:
            reload = True
            begin_shutdown("Code changed, reloading...")
    await server
    return reload


def run(host: str, port: int, debug: bool = False):
    """Run the webserver until Ctrl+C or SIGTERM. Used instead of Quart's `app.run()`
    so open websockets get closed on shutdown, and a second Ctrl+C forces an exit.

    With `debug`, the server also restarts itself whenever its code changes."""
    if asyncio.run(_serve(host, port, debug)):
        # Re-executes this process with the same arguments
        restart()
