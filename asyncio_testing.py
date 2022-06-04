# eccc-msc-amqp-alerts
# Copyright (C) 2022  Justin A. S. Bull
# See __init__.py for full notice
import asyncio
import random
from datetime import datetime
from typing import cast

# from .message_consumer import MessageConsumer


class FakeConsumer:
    async def random_work(self):
        wait = random.randrange(1, 5)
        print(f"[{datetime.now()}] Waiting {wait} seconds")
        await asyncio.sleep(wait)
        print(f"[{datetime.now()}] Done! {wait}")
        return wait

    async def run(self):
        try:
            while True:
                await self.random_work()
        except asyncio.CancelledError:
            print(f"[{datetime.now()}] Work cancelled! Stopping immediately.")


class Heartbeat:
    async def run(self):
        try:
            counter = 0
            while True:
                await asyncio.sleep(1)
                counter += 1
                print(f"[{datetime.now()}] BEAT! {counter}")
        except asyncio.CancelledError:
            print(f"[{datetime.now()}] BEAT CANCELLED! Cleaning up...")
            await asyncio.sleep(3)
            print(f"[{datetime.now()}] BEAT Cleaned up")


class MyApp:
    def __init__(self) -> None:
        self.consumer = FakeConsumer()
        self.beater = Heartbeat()

    async def main(self):
        print(f"[{datetime.now()}] starting..")
        try:
            gather_co = asyncio.gather(self.consumer.run(), self.beater.run())
            await gather_co
        except asyncio.CancelledError as e:
            # TODO: why is mypy always saying this is Unbound?
            gather_co = cast(asyncio.Future[tuple[None, None]], gather_co)
            print(
                f"[{datetime.now()}] Main app got cancelled {e}. Ended! {gather_co._state}"
            )


app = MyApp()
try:
    asyncio.run(app.main(), debug=True)
except KeyboardInterrupt:
    print(f"[{datetime.now()}] User-initiated keyboard interrupt. Cancelled all tasks")
