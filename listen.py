from types import FrameType
from typing import Optional
import sys
import signal
import pika
from pika.adapters.blocking_connection import BlockingChannel
from pika.exceptions import StreamLostError
from pika.spec import Basic
from pika.spec import BasicProperties
from pika.frame import Method
from wmo_header import decode_header as decode_wmo_header

connection_string = "amqps://anonymous:anonymous@dd.weather.gc.ca:5671"

exchange = "xpublic"
exchange_type = "topic"
subtopic = "alerts.#"
exchange_key = f"v02.post.{subtopic}"
# exchange_key = '#' # ALL
# exchange_key = '*.*.bulletins.alphanumeric.*.WA.#' # ALL
exchange_key = "*.*.bulletins.alphanumeric.*.#"  # ALL

my_queue_name = "q_anonymous.justinbull.all_alerts.123abc.abc123"

routing_keys_found: dict[str, int] = {}


def print_routing_keys():
    for k, v in routing_keys_found.items():
        print("{:<70} {:<100}".format(k, v))


def shutdown():
    print("[*] Shutting down...")
    channel.queue_unbind(
        queue=my_queue_name, exchange=exchange, routing_key=exchange_key
    )
    print("[*] Unbound queue...")
    channel.queue_delete(queue=my_queue_name)
    print("[*] Deleted queue...")
    channel.close()
    print("[*] Closed channel...")
    connection.close()
    print("[*] Closed connection...")


def signal_handler(sig: int, _frame: Optional[FrameType]):
    if sig == signal.SIGINT:
        print("[!] You pressed Ctrl+C or triggered SIGINT!")
    else:
        print(f"[!] Got signal: {signal.Signals(sig).name}")
    shutdown()
    print_routing_keys()
    sys.exit()


signal.signal(signal.SIGINT, signal_handler)

print(
    """[!] ❤️ Many thanks to ECCC for making this data open and accessible to the public. Required attribution notice follows...
    Data Source: Environment and Climate Change Canada
    https://eccc-msc.github.io/open-data/licence/readme_en/
"""
)

print(f"[*] Connecting to {connection_string}...")
connection = pika.BlockingConnection(pika.URLParameters(connection_string))

print("[*] Opening channel...")
channel = connection.channel()

print(f"[*] Creating queue (name: {my_queue_name})...")
declare_result: Method = channel.queue_declare(
    queue=my_queue_name, auto_delete=True, durable=False
)
queue_name = declare_result.method.queue

print(f'[*] Binding queue to "{exchange}" exchange (routing key: {exchange_key})...')
bind_result: Method = channel.queue_bind(
    queue=queue_name, exchange=exchange, routing_key=exchange_key
)


def on_message(
    channel: BlockingChannel,
    method: Basic.Deliver,
    properties: BasicProperties,
    body: bytes,
):
    routing_key: str = method.routing_key
    route_parts = routing_key.split(".")
    if not (route_parts[5].startswith("W") or route_parts[5].startswith("FL")):
        print(".", end="", flush=True)
        return
    if routing_key in routing_keys_found:
        routing_keys_found[routing_key] += 1
    else:
        routing_keys_found[routing_key] = 1
    print("\n--------------")
    print_routing_keys()

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


print("[*] Setting up callback...")
res = channel.basic_consume(queue_name, on_message_callback=on_message, auto_ack=True)
print(res)

print("[*] Consuming...")
try:
    channel.start_consuming()
except StreamLostError as e:
    print(f"[!] Damn! Encountered StreamLostError: {repr(e)}")

shutdown()
print_routing_keys()
