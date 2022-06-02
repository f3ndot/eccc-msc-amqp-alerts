# eccc-msc-amqp-alerts
# Copyright (C) 2022  Justin A. S. Bull
# See __init__.py for full notice

import os
from lxml import etree

_cwd = os.path.dirname(os.path.abspath(__file__))

_xmlschema_doc = etree.parse(f"{_cwd}/CAP-v1.2.xsd")
xmlschema = etree.XMLSchema(_xmlschema_doc)


class Alert:
    """Represents a parsed .cap file corresponding to the Canadian Profile (CAP-CP)
    extension of the Common Alert Protocol (CAP) version 1.2.

    Exposes the most meaningful structured data for this program.

    References:
    * https://docs.oasis-open.org/emergency/cap/v1.2/CAP-v1.2.html
    * https://www.publicsafety.gc.ca/cnt/mrgnc-mngmnt/mrgnc-prprdnss/npas/clf-en.aspx
    * https://www.publicsafety.gc.ca/cnt/mrgnc-mngmnt/mrgnc-prprdnss/capcp/index-en.aspx

    """

    # Frustrating that XPath 1.0 doesn't support default namespaces
    _CAPNS = "urn:oasis:names:tc:emergency:cap:1.2"
    _tree: etree._ElementTree

    _SUPPORTED_CAP_CP_EVENT = "profile:CAP-CP:Event:0.4"

    def __init__(self, bytes: bytes = None, path: str = None) -> None:
        """Pass in raw requests' response bytes to `bytes`"""
        if bytes is None and path is None:
            raise ValueError("Specify either path or bytes")
        elif bytes:
            self._tree = etree.ElementTree(etree.fromstring(bytes))
        elif path:
            self._tree = etree.parse(path)
        # NOTE: Alerts use the CAP-Canadian Profile (CAP-CP) standard, while a valid CAP
        # document, contains additional rules and values not checked here.
        #
        # See: https://www.publicsafety.gc.ca/cnt/mrgnc-mngmnt/mrgnc-prprdnss/capcp/index-en.aspx
        xmlschema.assertValid(self._tree)
        self._parse_relevent_data()

    def _parse_relevent_data(self):
        self.cp_event_code = self._parse_cp_event_code()

    def _parse_cp_event_code(self):
        N = self._CAPNS
        e_eventCode = self._tree.find(f"/{{{N}}}info/{{{N}}}eventCode")
        assert (
            e_eventCode.findtext(f"{{{N}}}valueName") == self._SUPPORTED_CAP_CP_EVENT
        ), "Unsupported CAP-CP Event version"
        return e_eventCode.findtext(f"{{{N}}}value")

    def __repr__(self) -> str:
        type_ = type(self)
        return f"<{type_.__qualname__}({self.__dict__})>"
