# eccc-msc-amqp-alerts
# Copyright (C) 2026  Justin A. S. Bull
# See __init__.py for full notice

import logging
import sys
from collections import deque
from typing import Deque

import pika.spec
import requests
import requests.exceptions
import urllib3.exceptions
from pika.adapters.blocking_connection import BlockingChannel

from .config import config
from .message_consumer import MessageConsumer
from .wmo_header import pretty_header as pretty_wmo_header

logger = logging.getLogger(__name__)
print("""
    ❤️ Many thanks to ECCC for making this data open and accessible to the public. Required attribution notice follows...

    Data Source: Environment and Climate Change Canada
    https://eccc-msc.github.io/open-data/licence/readme_en/
""")

recent_bulletins: Deque[str] = deque(maxlen=50)

# TODO: figure out what the most blessed way to introspect own version
user_agent = f"eccc-msc-amqp-alerts/0.1.0 (Python {'.'.join([str(i) for i in sys.version_info])})"

# ECCC's Datamart announces every new file with a message whose routing key mirrors
# the file's path on the server, with "/" swapped for ".":
#
#   v02.post.<YYYYMMDD>.WXO-DD.<product path...>
#
# Bulletins and alerts sit under these product paths:
#
#   bulletins.alphanumeric.<YYYYMMDD>.<T1T2>.<CCCC>.<HH>
#   alerts.cap.<YYYYMMDD>.<CCCC>.<HH>
#
# where T1T2 is the bulletin's WMO data type designators (eg. "WW" for warnings, see
# https://community.wmo.int/ahl-table-definitions), CCCC the issuing centre and HH the
# UTC hour it was issued. eg.
#
#   v02.post.20261031.WXO-DD.bulletins.alphanumeric.20261031.SA.CYXC.15
#
# In AMQP topic patterns "*" matches exactly one dot-separated word and "#" matches
# zero or more, so the patterns below wildcard the dates.
BULLETINS_ALL_ROUTING_KEY = "v02.post.*.WXO-DD.bulletins.alphanumeric.#"
# Format with `t1t2=` to subscribe to a single bulletin type, eg. "WW"
BULLETINS_TOPIC_ROUTING_KEY = "v02.post.*.WXO-DD.bulletins.alphanumeric.*.{t1t2}.#"
ALERTS_ROUTING_KEY = "v02.post.*.WXO-DD.alerts.#"

# ECCC implores consumers to fetch from HPFX to keep loads low on DD. Message paths are
# relative to the server root, so they work on either host.
HPFX_HOST = "https://hpfx.collab.science.gc.ca/"


def fetch_bulletin_text(original_host: str, path: str):
    logger.debug(f"Fetching bulletin: host={original_host} path={path}")
    hpfx_url = f"{HPFX_HOST}{path}"
    # TODO: exponential backoff and retry. TODO: use request sessions?
    response = requests.get(
        hpfx_url,
        headers={"User-Agent": user_agent},
        timeout=10,
    )
    if not response.ok:  # fall back to original source (probably always DD)
        logger.warning(
            f"Unable to fetch from HPFX {hpfx_url} ({response.status_code} {response.reason}), falling back to original host: "
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
    bulletin_text = response.text
    print(bulletin_text)
    recent_bulletins.append(bulletin_text)
    return bulletin_text


def on_bulletin_message(
    _channel: BlockingChannel,
    method: pika.spec.Basic.Deliver,
    properties: pika.spec.BasicProperties,
    body: bytes,
):
    _body = body.decode()
    logger.debug({"method": method, "properties": properties, "body": _body})
    _timestamp, host, path = _body.split(" ")
    wmo_gts_comms_header = " ".join(
        path.split("/")[-1].replace("_", " ").split(" ")[0:3]
    ).rstrip()
    logger.debug(f"WMO GTS Abbreviated Header Section: {wmo_gts_comms_header}")
    logger.info(f"WMO GTS Header:\n{pretty_wmo_header(wmo_gts_comms_header)}")
    try:
        text = fetch_bulletin_text(host, path)
        logger.info("End of bulletin")
        return text
    except (
        TimeoutError,
        requests.exceptions.RequestException,
        urllib3.exceptions.MaxRetryError,
    ) as e:
        logger.warning(
            f"Timed out trying to fetch bulletin text. Returning None. Exception: {repr(e)}"
        )
        return None


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


consumer = MessageConsumer()

if config.bulletins:
    if config.bulletin_topics == ["all"]:
        consumer.subscribe_to_topic(
            name="bulletins_all",
            routing_key=BULLETINS_ALL_ROUTING_KEY,
            callback=on_bulletin_message,
        )
    else:
        for topic in config.bulletin_topics:
            consumer.subscribe_to_topic(
                name=f"bulletins_{topic}",
                routing_key=BULLETINS_TOPIC_ROUTING_KEY.format(t1t2=topic),
                callback=on_bulletin_message,
            )
if config.alerts:
    consumer.subscribe_to_topic(
        name="alerts",
        routing_key=ALERTS_ROUTING_KEY,
        callback=on_alert_message,
    )


def run(print_stats=False):
    try:
        print("🔌 Connecting... ", end="", flush=True)
        consumer.run(on_started=lambda: print("OK! Now listening for messages... 👂"))
    except KeyboardInterrupt:
        print("🛎️ Keyboard interrupt received! Shutting down...")
        consumer.stop()
        if print_stats:
            print("📊 Statistics!")
            print(consumer.stats)
