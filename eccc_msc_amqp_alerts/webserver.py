# eccc-msc-amqp-alerts
# Copyright (C) 2022  Justin A. S. Bull
# See __init__.py for full notice

import asyncio
import json
import logging
from datetime import datetime
from quart import Quart, render_template, websocket

from .types import OnMessageAIOQueue
from .message_consumer import MessageConsumer
from .listen import consumer

logger = logging.getLogger(__name__)
app = Quart(__name__)


class ConsumerOrchestrator:
    def __init__(self, consumer: MessageConsumer) -> None:
        self.consumer = consumer
        self.consumer.on_any_message = self.push_to_websocket_queue
        self.websockets: set[OnMessageAIOQueue] = set()
        self.dump_queue: OnMessageAIOQueue = asyncio.Queue(maxsize=100)

    def push_to_websocket_queue(self, routing_key: str, body: bytes, ret):
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

    async def run(self):
        # try:
        print("🔌 Connecting... ", end="", flush=True)
        self.consumer.run(
            loop=asyncio.get_event_loop(),
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


consumer_orc = ConsumerOrchestrator(consumer)


@app.before_serving
async def start_amqp_listening():
    app.add_background_task(consumer_orc.run)


@app.route("/")
async def index():
    return await render_template("index.html")


@app.route("/current_queues")
async def current_queues():
    websocket_queues = {}
    for wsq in consumer_orc.websockets:
        websocket_queues[repr(wsq)] = wsq.qsize()
    return {
        "dump_queue": consumer_orc.dump_queue.qsize(),
        "websocket_queues": websocket_queues,
    }


@app.route("/dump")
async def dump():
    items = []
    try:
        while True:
            item = consumer_orc.dump_queue.get_nowait()
            items.append(
                {
                    "routing_key": item[0],
                    "message": item[1].decode(),
                    "body": item[2],
                }
            )
    except asyncio.QueueEmpty:
        return {"items": items}


@app.websocket("/ws")
async def ws():
    queue: OnMessageAIOQueue = asyncio.Queue(maxsize=1)
    try:
        print(f"Adding {queue}")
        consumer_orc.websockets.add(queue)
        # await consumer_orc.send_websocket_from_queue_get(queue)
        await websocket.send(
            json.dumps(
                {
                    "sysmsg": "Hello from websocket server! Queue provisioned, awaiting messages from AMQP consumer code"
                }
            )
        )
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
        print(f"Removing {queue}")
        consumer_orc.websockets.remove(queue)
