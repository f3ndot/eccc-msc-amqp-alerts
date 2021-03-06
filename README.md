# ECCC MSC AMQP Alerts

Subscribe and listen to Environment and Climate Change Canada's (ECCC) Meteorological
Service of Canada (MSC) Datamart AMQP server for timely notification of all and any
meteorological alerts and bulletins.

This is still in active development and may have many incomplete features or behaviours.

![Main workflow](https://github.com/f3ndot/eccc-msc-amqp-alerts/actions/workflows/python-app.yml/badge.svg)

## Installation

```
pip install .
```

or

```
poetry install
```

## Running

```
python -m eccc_msc_amqp_alerts -v
```

or

```
poetry run python -m eccc_msc_amqp_alerts -v
```

## Usage

You should probably use `-v` when running the program.

```
usage: eccc_msc_amqp_alerts [-h] [-d] [-v] [-s] [-w]

Listen to and print alerts and bulletins from Environment and Climate Change Canada's
Metereological Service Canada Datamart AMQP server

optional arguments:
  -h, --help         show this help message and exit
  -d, --debug        print lots of debugging statements
  -v, --verbose      be verbose, show what's going on
  -s, --print-stats  print statistics on exit
  -w, --web-server   EXPERIMENTAL: Run ECCC MSC AMQP Alerts as a webserver with sockets

Copyright (C) 2022  Justin A. S. Bull

Data Source: Environment and Climate Change Canada
https://eccc-msc.github.io/open-data/licence/readme_en/

This program comes with ABSOLUTELY NO WARRANTY. This is free software, and you are
welcome to redistribute it under certain conditions.
```

## TODO

- Show decoded WHO AHL in a spot
- Consider spawning queue listener and webserver as multiple processes for better throughput on `all` topics
- Make this an optionally importable Python library and people pass in their callback hooks?
- Finish parsing alert CAP files and display a fun way (make own pseudo alphanumeric equivalent and maybe an ascii or ansi ⚠️)
- Handle recovering previously declared queues from a former session (delete or purge first?)
- Recover from 'soft fails' with Pika (eg restarting a channel or connection)
- Handle graceful remote shutdowns with a restart attempt before giving up
- Simplify message parsing into dataclass/de-dupe AHL parsing
- CAP files don't get in the way of "loading previous bulletins" (differentiate between alphanum and CAP messages as dataclasses)

## Acknowledgements

❤️ Many thanks to ECCC for making this data open and accessible to the public.

[Data Source: Environment and Climate Change Canada](https://eccc-msc.github.io/open-data/licence/readme_en/)

## Copyright

Copyright © 2022 Justin A. S. Bull

See [`eccc_msc_amqp_alerts/__init__.py`](eccc_msc_amqp_alerts/__init__.py) for full notice
