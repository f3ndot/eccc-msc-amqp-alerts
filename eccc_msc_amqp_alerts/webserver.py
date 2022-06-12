# eccc-msc-amqp-alerts
# Copyright (C) 2022  Justin A. S. Bull
# See __init__.py for full notice

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Optional
from quart import Quart, render_template, websocket

from .types import OnMessageAIOQueue
from .message_consumer import MessageConsumer
from .listen import consumer

logger = logging.getLogger(__name__)


class QuartWithConsumerOrc(Quart):
    consumer_orc: "ConsumerOrchestrator"


app = QuartWithConsumerOrc(__name__)


class ConsumerOrchestrator:
    def __init__(self, consumer: MessageConsumer) -> None:
        self.last_bulletin: tuple[str, bytes, Any] | None = None
        self.consumer = consumer
        self.consumer.on_any_message = self.push_to_websocket_queue
        self.websockets: set[OnMessageAIOQueue] = set()
        self.dump_queue: OnMessageAIOQueue = asyncio.Queue(maxsize=100)

    def push_to_websocket_queue(self, routing_key: str, body: bytes, ret):
        self.last_bulletin = (routing_key, body, ret)
        ret_len = len(ret) if ret else "N/A"
        logger.info(
            f"push_to_websocket_queue called with {(routing_key, body, f'ret_size={ret_len}')}"
        )
        try:
            logger.info(
                f"GOT A MESSAGE! Adding {(routing_key, body, ret)} to dump queue {self.dump_queue} (currently {self.dump_queue.qsize()})"
            )
            self.dump_queue.put_nowait((routing_key, body, ret))
        except asyncio.QueueFull:
            logger.info(f"SKIPPING PUSH {(routing_key, body, ret)} for full dump queue")
        for ws_queue in self.websockets:
            try:
                ws_queue.put_nowait((routing_key, body, ret))
            except asyncio.QueueFull:
                print(
                    f"[{datetime.now()}][{self}] SKIPPING PUSH {(routing_key, body, f'ret_size={ret_len}')} for full websocket queue {ws_queue}"
                )

    async def run(self, loop):
        # try:
        print("🔌 Connecting... ", end="", flush=True)
        self.consumer.run(
            loop=loop,
            on_started=lambda: print("OK! Now listening for messages... 👂"),
        )
        # except asyncio.CancelledError:
        # finally:
        #     print(f"[{datetime.now()}][{self}] Listening system cancelled")
        #     self.consumer.stop()
        #     print("📊 Statistics!")
        #     print(self.consumer.stats)

    # async def send_websocket_from_queue_get(self, queue: OnMessageAIOQueue):
    #     while True:
    #         data = await queue.get()
    #         await websocket.send(data[0])


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
    for wsq in app.consumer_orc.websockets:
        websocket_queues[repr(wsq)] = wsq.qsize()
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
            items.append(
                {
                    "routing_key": item[0],
                    "message": item[1].decode(),
                    "body": item[2],
                }
            )
    except asyncio.QueueEmpty:
        return {"items": items}


async def ws_keepalive():
    while True:
        await asyncio.sleep(45)
        logger.info("Sending WS heartbeat...")
        await websocket.send(json.dumps({"heartbeat": str(datetime.now())}))


@app.websocket("/ws")
async def ws():
    task: Optional[asyncio.Task] = None
    queue: OnMessageAIOQueue = asyncio.Queue(maxsize=1)
    try:
        logger.info(f"Adding {queue}")
        app.consumer_orc.websockets.add(queue)
        # await consumer_orc.send_websocket_from_queue_get(queue)
        await websocket.send(
            json.dumps(
                {
                    "sysmsg": "Hello from websocket server! Queue provisioned, awaiting messages from live feed"
                }
            )
        )
        task = asyncio.create_task(ws_keepalive())
        if app.consumer_orc.last_bulletin is not None:
            await websocket.send(
                json.dumps(
                    {"sysmsg": "Loading last received bulletin while you wait :-)"}
                )
            )
            item = app.consumer_orc.last_bulletin
            payload = json.dumps(
                {
                    "routing_key": item[0],
                    "message": item[1].decode(),
                    "body": item[2],
                }
            )
            await websocket.send(payload)
        while True:
            item = await queue.get()
            payload = json.dumps(
                {
                    "routing_key": item[0],
                    "message": item[1].decode(),
                    "body": item[2],
                }
            )
            await websocket.send(payload)
    finally:
        logger.info("stopping ws keepalive")
        if task:
            task.cancel()
        logger.info(f"Removing {queue}")
        app.consumer_orc.websockets.remove(queue)
