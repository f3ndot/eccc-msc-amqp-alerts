# eccc-msc-amqp-alerts
# Copyright (C) 2022  Justin A. S. Bull
# See __init__.py for full notice

import asyncio
import dataclasses
import json
import logging
from datetime import datetime
from quart import Quart, render_template, websocket

from .types import OnMessageAIOQueue
from .message_consumer import MessageConsumer
from .listen import consumer

logger = logging.getLogger(__name__)


class QuartWithConsumerOrc(Quart):
    consumer_orc: "ConsumerOrchestrator"


app = QuartWithConsumerOrc(__name__)


@dataclasses.dataclass(repr=False)
class AmqpBulletinMessage:
    routing_key: str
    message: str
    bulletin: str | None

    @property
    def region(self):
        # FIXME: doesn't work on alert CAP messages.. different URL format. Probably
        # because only Canadian CAPs come thru. Eg message:
        #   20220612164605.996 https://dd4.weather.gc.ca /alerts/cap/20220612/LAND/16/T_MBCN00_C_LAND_202206121643_1119167019.cap
        # Should probably parse CAP to determine 'region' or just assume CA.
        #
        # TODO: parse body into its components as defined by MSC Datamart's scheme
        return self.message.split(" ")[-1].split("/")[-1][2:4]

    @property
    def bulletin_len(self):
        return len(self.bulletin) if self.bulletin else "N/A"

    def __repr__(self) -> str:
        repr_fields = ", ".join(
            [f"{k}={v}" for k, v in self.__dict__.items() if k != "bulletin"]
        )
        return (
            self.__class__.__qualname__
            + f"({repr_fields}, region={self.region}), bulletin_len={self.bulletin_len}"
        )

    def jsondict(self):
        d = self.__dict__
        d["region"] = self.region
        return d


@dataclasses.dataclass
class WebsocketConnection:
    queue: OnMessageAIOQueue
    config: dict = dataclasses.field(default_factory=lambda: {"region_filter": "any"})


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
        try:
            self.dump_queue.put_nowait(message)
        except asyncio.QueueFull:
            logger.info(
                f"SKIPPING PUSH {message} to dump queue {self.dump_queue} (is full)"
            )
        for ws_conn in self.websockets.values():
            self._push_to_ws_queue(message=message, conn=ws_conn)

    def _push_to_ws_queue(
        self, message: AmqpBulletinMessage, conn: WebsocketConnection
    ):
        try:
            _filter = conn.config["region_filter"]
            if _filter == "any" or message.region == _filter:
                conn.queue.put_nowait(message)
            else:
                logger.info(
                    f"Skipping push {message} due to filter {_filter} on queue {id(conn.queue)}"
                )
        except asyncio.QueueFull:
            logger.warn(
                f"SKIPPING PUSH {message} for full websocket queue {id(conn.queue)}"
            )

    async def run(self, loop):
        print("🔌 Connecting... ", end="", flush=True)
        self.consumer.run(
            loop=loop,
            on_started=lambda: print("OK! Now listening for messages... 👂"),
        )


@app.before_serving
async def start_amqp_listening():
    logger.info("Starting AMQP listening alongside Quart")
    loop = asyncio.get_event_loop()
    app.consumer_orc = ConsumerOrchestrator(consumer)
    loop.create_task(app.consumer_orc.run(loop=loop))


@app.after_serving
async def shutdown():
    max_wait_secs = 5
    logger.info(
        f"Gracefully stopping AMQP listening (waiting up to {max_wait_secs}s)..."
    )
    try:
        await app.consumer_orc.consumer.stop_and_wait(timeout=max_wait_secs)
        logger.info("Gracefully STOPPED AMQP listening!")
    except asyncio.TimeoutError:
        logger.info(f"TIMED OUT! Waited {max_wait_secs}s. Forcefully shutting down...")


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
                {"sysmsg": f"Changed to region filter to {data['region_filter']}"}
            )


@app.websocket("/ws")
async def ws():
    tasks: list[asyncio.Task] = []
    queue: OnMessageAIOQueue = asyncio.Queue(maxsize=1)
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
            item = app.consumer_orc.last_bulletin
            await websocket.send_json(item.jsondict())
        while True:
            item = await queue.get()
            await websocket.send_json(item.jsondict())
    finally:
        logger.info("stopping ws keepalive")
        for task in tasks:
            task.cancel()
        logger.info(f"Removing {queue}")
        del app.consumer_orc.websockets[id(queue)]
