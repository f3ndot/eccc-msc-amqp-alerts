# ECCC MSC AMQP Alerts

Subscribe and listen to Environment and Climate Change Canada's (ECCC) Meteorological
Service of Canada (MSC) Datamart AMQP server for timely notification of all and any
meteorological alerts and bulletins.

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
python -m eccc_msc_amqp_alerts
```

or

```
poetry run python -m eccc_msc_amqp_alerts
```

## TODO:

- Settle on a web framework
- Figure out data structure and pattern for efficiently passing bulletins/alert to web framework
- Settle many queues vs 1 queue with client-side filtering debate
- Replace prints with `logging` pattern
- Fetch and parse alert CAP files in a fun way (make own pseudo alphanumeric equivalent and maybe an ascii or ansi ⚠️)
- Handle if channel is already closed on shutdown for queue unbinds/delates
- Handle recovering previously declared queues from a former session (delete or purge first?)
- Recover from 'soft fails' with Pika (eg restarting a channel or connection)

---

❤️ Many thanks to ECCC for making this data open and accessible to the public.

[Data Source: Environment and Climate Change Canada](https://eccc-msc.github.io/open-data/licence/readme_en/)

---

## Copyright

Copyright (C) 2022 Justin A. S. Bull

See [`eccc-msc-amqp-alerts/__init__.py`](eccc-msc-amqp-alerts/__init__.py) for full notice
