# eccc-msc-amqp-alerts
# Copyright (C) 2022  Justin A. S. Bull
# See __init__.py for full notice

import argparse
import logging

parser = argparse.ArgumentParser(
    prog="eccc_msc_amqp_alerts",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    description="Listen to and print alerts and bulletins from Environment and Climate Change Canada's Metereological Service Canada Datamart AMQP server",
    epilog="""Copyright (C) 2022  Justin A. S. Bull

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
args = parser.parse_args()

logging.basicConfig(
    level=args.loglevel,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

from .listen import run  # noqa: E402

run()
