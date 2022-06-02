# eccc-msc-amqp-alerts
# Copyright (C) 2022  Justin A. S. Bull
# See __init__.py for full notice

from typing import Deque
import logging
import sys
import requests
import pika.spec
from datetime import datetime
from collections import deque
from pika.adapters.blocking_connection import BlockingChannel
from .wmo_header import pretty_header as pretty_wmo_header
from .message_consumer import MessageConsumer
from .config import config


logger = logging.getLogger(__name__)
print(
    """
    ❤️ Many thanks to ECCC for making this data open and accessible to the public. Required attribution notice follows...

    Data Source: Environment and Climate Change Canada
    https://eccc-msc.github.io/open-data/licence/readme_en/
"""
)

recent_bulletins: Deque[str] = deque(maxlen=50)

# TODO: figure out what the most blessed way to introspect own version
user_agent = f"eccc-msc-amqp-alerts/0.1.0 (Python {'.'.join([str(i) for i in sys.version_info])})"


def fetch_bulletin_text(body_timestamp, original_host: str, path: str):
    logger.debug(
        f"Fetching bulletin: body_timestamp={body_timestamp} host={original_host} path={path}"
    )
    timestamp = datetime.strptime(body_timestamp, "%Y%m%d%H%M%S.%f")
    # ECCC implores consumers to use the HPFX host to keep loads low on DD
    hpfx_url = (
        f"https://hpfx.collab.science.gc.ca/{timestamp.strftime('%Y%m%d')}/WXO-DD{path}"
    )
    # TODO: exponential backoff and retry. TODO: use request sessions?
    response = requests.get(
        hpfx_url,
        headers={"User-Agent": user_agent},
        timeout=10,
    )
    if not response.ok:  # fall back to original source (probably always DD)
        logger.warn(
            f"Unable to fetch from HPFX ({hpfx_url}), falling back to original host: "
            f"{original_host}{path}"
        )
        response = requests.get(
            f"{original_host}{path}",
            headers={"User-Agent": user_agent},
            timeout=10,
        )

    if not response.ok:
        logger.error(
            f"Unable to get bulletin from either HPFX or {original_host}{path}"
        )
        return

    logger.info("Fetched Bulletin:")
    print(response.text)
    recent_bulletins.append(response.text)


def on_bulletin_message(
    _channel: BlockingChannel,
    method: pika.spec.Basic.Deliver,
    properties: pika.spec.BasicProperties,
    body: bytes,
):
    _body = body.decode()
    logger.debug({"method": method, "properties": properties, "body": _body})
    timestamp, host, path = _body.split(" ")
    wmo_gts_comms_header = " ".join(
        path.split("/")[-1].replace("_", " ").split(" ")[0:3]
    ).rstrip()
    logger.debug(f"WMO GTS Abbreviated Header Section: {wmo_gts_comms_header}")
    logger.info(f"WMO GTS Header:\n{pretty_wmo_header(wmo_gts_comms_header)}")
    fetch_bulletin_text(timestamp, host, path)
    logger.info("End of bulletin")
    # logger.debug("on_bulletin_message complete")


def on_alert_message(
    _channel: BlockingChannel,
    method: pika.spec.Basic.Deliver,
    properties: pika.spec.BasicProperties,
    body: bytes,
):
    _body = body.decode()
    print(f"⚠️⚠️⚠️ ALERT! ALERT! ALERT! ⚠️⚠️⚠️ - {_body}")
    logger.debug({"method": method, "properties": properties, "body": _body})
    logger.debug("on_alert_message complete")


def run():
    consumer = MessageConsumer()
    try:
        if config.bulletins:
            if config.bulletin_topics == ["all"]:
                consumer.subscribe_to_topic(
                    name="bulletins_all",
                    routing_key="*.*.bulletins.alphanumeric.*.#",
                    callback=on_bulletin_message,
                )
            else:
                for topic in config.bulletin_topics:
                    consumer.subscribe_to_topic(
                        name=f"bulletins_{topic}",
                        routing_key=f"*.*.bulletins.alphanumeric.*.{topic}.#",
                        callback=on_bulletin_message,
                    )
        if config.alerts:
            consumer.subscribe_to_topic(
                name="alerts",
                routing_key="*.*.alerts.#",
                callback=on_alert_message,
            )

        print("🔌 Connecting... ", end="", flush=True)
        consumer.run(on_started=lambda: print("OK! Now listening for messages... 👂"))
    except KeyboardInterrupt:
        print("🛎️ Keyboard interrupt received! Shutting down...")
        consumer.stop()
