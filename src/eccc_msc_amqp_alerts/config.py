# eccc-msc-amqp-alerts
# Copyright (C) 2026  Justin A. S. Bull
# See __init__.py for full notice

from configparser import ConfigParser

from .wmo_header import gts_tables


class Config(object):
    PATH_TO_CONFIGURATION_INI = "config.ini"

    _parser = ConfigParser()

    def __init__(self, path=PATH_TO_CONFIGURATION_INI) -> None:
        self._parser.read(path)
        self.name = self._parser.get("eccc-msc-amqp-alerts", "name")
        self.bulletins = self._parser.getboolean("bulletins", "enabled")
        self.alerts = self._parser.getboolean("alerts", "enabled")
        self.bulletin_topics = self._expand_bulletin_topic()
        # Optional section, so older config.ini files without it keep working
        self.webserver_host = self._parser.get(
            "webserver", "host", fallback="127.0.0.1"
        )
        self.webserver_port = self._parser.getint("webserver", "port", fallback=5000)

    def _expand_bulletin_topic(self):
        expanded_topics = []
        for topic in self._parser.get("bulletins", "topics").split(","):
            if topic == "all":
                return ["all"]
            if len(topic) == 1:
                for subtopic in gts_tables.tableA[topic]["T2"].keys():
                    expanded_topics.append(f"{topic}{subtopic}")
            else:
                expanded_topics.append(topic)
        return expanded_topics

    def __repr__(self) -> str:
        type_ = type(self)
        return f"<{type_.__qualname__}({self.__dict__})>"


config = Config()
