# eccc-msc-amqp-alerts
# Copyright (C) 2026  Justin A. S. Bull
# See __init__.py for full notice

import argparse
import logging

parser = argparse.ArgumentParser(
    prog="eccc_msc_amqp_alerts",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    description="Listen to and print alerts and bulletins from Environment and Climate Change Canada's Metereological Service Canada Datamart AMQP server",
    epilog="""Copyright (C) 2026  Justin A. S. Bull

Data Source: Environment and Climate Change Canada
https://eccc-msc.github.io/open-data/licence/readme_en/

This program comes with ABSOLUTELY NO WARRANTY. This is free software, and you are welcome to redistribute it under certain conditions.
""",
)
parser.add_argument(
    "-d",
    "--debug",
    help="print lots of debugging statements",
    action="store_const",
    dest="loglevel",
    const=logging.DEBUG,
    default=logging.WARNING,
)
parser.add_argument(
    "-v",
    "--verbose",
    help="be verbose, show what's going on",
    action="store_const",
    dest="loglevel",
    const=logging.INFO,
)
parser.add_argument(
    "-s",
    "--print-stats",
    action="store_true",
    help="print statistics on exit",
    dest="print_stats",
)
parser.add_argument(
    "-w",
    "--web-server",
    action="store_true",
    help="EXPERIMENTAL: Run ECCC MSC AMQP Alerts as a webserver with sockets",
    dest="web_server",
)
parser.add_argument(
    "--host",
    help="address for the webserver to bind to, eg. 0.0.0.0 for all interfaces. "
    "Overrides config.ini (default: 127.0.0.1). Requires -w",
)
parser.add_argument(
    "-p",
    "--port",
    type=int,
    help="port for the webserver to listen on. Overrides config.ini "
    "(default: 5000). Requires -w",
)
parsed_args = parser.parse_args()

logging.basicConfig(
    level=parsed_args.loglevel,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
if parsed_args.loglevel <= logging.INFO:
    # It's useful to see heartbeats run at an info level
    logging.getLogger("pika.heartbeat").setLevel(logging.DEBUG)

if parsed_args.web_server:
    from .config import config
    from .webserver import app

    app.run(
        host=(
            parsed_args.host if parsed_args.host is not None else config.webserver_host
        ),
        port=(
            parsed_args.port if parsed_args.port is not None else config.webserver_port
        ),
        debug=(parsed_args.loglevel == logging.DEBUG),
    )
else:
    from .listen import run

    run(print_stats=parsed_args.print_stats)
