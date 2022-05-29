import pika.spec
from pika.adapters.blocking_connection import BlockingChannel
from .wmo_header import decode_header as decode_wmo_header
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


def on_bulletin_message(
    _channel: BlockingChannel,
    method: pika.spec.Basic.Deliver,
    properties: pika.spec.BasicProperties,
    body: bytes,
):
    routing_key: str = method.routing_key
    route_parts = routing_key.split(".")
    if not (route_parts[5].startswith("W") or route_parts[5].startswith("FL")):
        print(".", end="", flush=True)
        return
    _timestamp, _host, path = body.decode().split(" ")
    wmo_gts_comms_header = " ".join(
        path.split("/")[-1].replace("_", " ").split(" ")[0:3]
    ).rstrip()
    decoded_header = decode_wmo_header(wmo_gts_comms_header)
    print(
        f"""method: {repr(method)}
properties: {repr(properties)}
body: {body.decode()}
decoded: {decoded_header}

"""
    )


def on_alert_message(
    _channel: BlockingChannel,
    method: pika.spec.Basic.Deliver,
    properties: pika.spec.BasicProperties,
    body: bytes,
):
    print("⚠️⚠️⚠️ ALERT! ALERT! ALERT! ⚠️⚠️⚠️")
    print(body.decode())
    print(
        f"""method: {repr(method)}
properties: {repr(properties)}
body: {body.decode()}

"""
    )


def run():
    consumer = MessageConsumer()
    try:
        if config.getboolean("bulletins"):
            consumer.subscribe_to_topic(
                name="bulletins",
                routing_key="*.*.bulletins.alphanumeric.#",
                callback=on_bulletin_message,
            )
        if config.getboolean("alerts"):
            consumer.subscribe_to_topic(
                name="alerts",
                routing_key="*.*.alerts.#",
                callback=on_alert_message,
            )
        consumer.consume()
    except Exception:
        consumer.shutdown()
        raise
