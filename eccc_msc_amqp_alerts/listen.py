# eccc-msc-amqp-alerts
# Copyright (C) 2022  Justin A. S. Bull
# See __init__.py for full notice

from typing import Deque
import sys
import requests
import pprint
import pika.spec
from datetime import datetime
from collections import deque
from pika.adapters.blocking_connection import BlockingChannel
from .wmo_header import pretty_header as pretty_wmo_header
from .message_consumer import MessageConsumer
from .config import config

# exchange_key = '*.*.bulletins.alphanumeric.*.WA.#' # ALL
# exchange_key = "*.*.bulletins.alphanumeric.*.#"  # ALL


print(
    """[!] ❤️ Many thanks to ECCC for making this data open and accessible to the public. Required attribution notice follows...

    Data Source: Environment and Climate Change Canada
    https://eccc-msc.github.io/open-data/licence/readme_en/
"""
)

recent_bulletins: Deque[str] = deque(maxlen=50)

# TODO: figure out what the most blessed way to introspect own version
user_agent = f"eccc-msc-amqp-alerts/0.1.0 (Python {'.'.join([str(i) for i in sys.version_info])})"


def fetch_bulletin_text(body_timestamp, original_host: str, path: str):
    timestamp = datetime.strptime(body_timestamp, "%Y%m%d%H%M%S.%f")
    # ECCC implores consumers to use the HPFX host to keep loads low on DD
    hpfx_url = (
        f"https://hpfx.collab.science.gc.ca/{timestamp.strftime('%Y%m%d')}/WXO-DD{path}"
    )
    # TODO: exponential backoff and retry
    response = requests.get(
        hpfx_url,
        headers={"User-Agent": user_agent},
        timeout=30,
    )
    if not response.ok:  # fall back to original source (probably always DD)
        print(
            f"[*] Unable to fetch from HPFX, falling back to original host {original_host}"
        )
        response = requests.get(
            f"{original_host}{path}",
            headers={"User-Agent": user_agent},
            timeout=30,
        )

    if not response.ok:
        print(f"[!] Unable to get bulletin from either HPFX or {original_host}{path}")
        return

    print(response.text)
    recent_bulletins.append(response.text)


def on_bulletin_message(
    _channel: BlockingChannel,
    method: pika.spec.Basic.Deliver,
    properties: pika.spec.BasicProperties,
    body: bytes,
):
    timestamp, host, path = body.decode().split(" ")
    wmo_gts_comms_header = " ".join(
        path.split("/")[-1].replace("_", " ").split(" ")[0:3]
    ).rstrip()
    print(wmo_gts_comms_header)
    print("==================")
    print(pretty_wmo_header(wmo_gts_comms_header))
    print("=====================================================================")
    fetch_bulletin_text(timestamp, host, path)
    print("=====================================================================\n")
    # TODO make this all debug loggering
    # pprint.pprint({"header": decoded_header, "body": body.decode()})


def on_alert_message(
    _channel: BlockingChannel,
    method: pika.spec.Basic.Deliver,
    properties: pika.spec.BasicProperties,
    body: bytes,
):
    print("⚠️⚠️⚠️ ALERT! ALERT! ALERT! ⚠️⚠️⚠️")
    # TODO make this all debug loggering
    pprint.pprint({"method": method, "properties": properties, "body": body.decode()})


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
        consumer.consume()
    except Exception:
        consumer.shutdown()
        raise
