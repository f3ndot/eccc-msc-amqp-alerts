from configparser import ConfigParser

_configuration = ConfigParser()
_configuration.read("config.ini")
config = _configuration["eccc-msc-amqp-alerts"]
