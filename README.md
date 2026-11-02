# ECCC MSC AMQP Alerts

Subscribe and listen to Environment and Climate Change Canada's (ECCC) Meteorological
Service of Canada (MSC) Datamart AMQP server for timely notification of all and any
meteorological alerts and bulletins.

This is still in active development and may have many incomplete features or behaviours.

![Main workflow](https://github.com/f3ndot/eccc-msc-amqp-alerts/actions/workflows/python-app.yml/badge.svg)

## Installation

This project uses [uv](https://docs.astral.sh/uv/) and requires Python 3.15. uv will
download a matching Python for you if you don't have one.

```
uv sync
```

or, without uv:

```
pip install .
```

## Running

Settings live in `config.ini` in the directory you run the program from.

```
uv run python -m eccc_msc_amqp_alerts -v
```

or, if installed with pip:

```
python -m eccc_msc_amqp_alerts -v
```

## Usage

You should probably use `-v` when running the program.

The web server (`-w`) listens on `127.0.0.1:5000` by default. Change that with `host` and
`port` in the `[webserver]` section of `config.ini`, or with the `--host` and `--port`
flags, which override `config.ini`. eg. to serve on all interfaces on port 8080:

```
uv run python -m eccc_msc_amqp_alerts -v -w --host 0.0.0.0 --port 8080
```

On macOS, port 5000 is usually taken by AirPlay Receiver, so you'll likely want a
different port there.

To run the web server on a server behind nginx, see [`deploy/`](deploy/README.md).

```
usage: eccc_msc_amqp_alerts [-h] [-d] [-v] [-s] [-w] [--host HOST] [-p PORT]

Listen to and print alerts and bulletins from Environment and Climate Change Canada's
Metereological Service Canada Datamart AMQP server

options:
  -h, --help         show this help message and exit
  -d, --debug        print lots of debugging statements. With -w, also reload the
                     webserver when its code changes
  -v, --verbose      be verbose, show what's going on
  -s, --print-stats  print statistics on exit
  -w, --web-server   EXPERIMENTAL: Run ECCC MSC AMQP Alerts as a webserver with sockets
  --host HOST        address for the webserver to bind to, eg. 0.0.0.0 for all
                     interfaces. Overrides config.ini (default: 127.0.0.1). Requires -w
  -p, --port PORT    port for the webserver to listen on. Overrides config.ini (default:
                     5000). Requires -w

Copyright (C) 2026  Justin A. S. Bull

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
- Handle graceful remote shutdowns with a restart attempt before giving up
- Simplify message parsing into dataclass/de-dupe AHL parsing
- CAP files don't get in the way of "loading previous bulletins" (differentiate between alphanum and CAP messages as dataclasses)

## Acknowledgements

❤️ Many thanks to ECCC for making this data open and accessible to the public.

[Data Source: Environment and Climate Change Canada](https://eccc-msc.github.io/open-data/licence/readme_en/)

## Copyright

Copyright © 2026 Justin A. S. Bull

See [`eccc_msc_amqp_alerts/__init__.py`](eccc_msc_amqp_alerts/__init__.py) for full notice
