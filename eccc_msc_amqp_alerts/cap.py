# eccc-msc-amqp-alerts
# Copyright (C) 2022  Justin A. S. Bull
# See __init__.py for full notice

import os
import logging
from lxml import etree

logger = logging.getLogger(__name__)

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
    _ns = {"x": _CAPNS}

    _tree: etree._ElementTree

    _SUPPORTED_CAP_CP = "profile:CAP-CP:0.4"
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
        self._assert_supported_cap_cp()

    def _assert_supported_cap_cp(self):
        # TODO: is this more readable and faster than xpath or elementpath?
        codes = list(self._tree.getroot().iterchildren(tag=self._nstag("code")))
        logger.debug(f"<code>'s: {[c.text for c in codes]}")
        assert any(
            [c.text == self._SUPPORTED_CAP_CP for c in codes]
        ), "Unsupported CAP-CP version or not a CAP-CP file"

    def parse(self):
        self.cp_eventCode = self._parse_cp_eventCode()

    def _parse_cp_eventCode(self):
        eventCodes = self._tree.xpath("./x:info/x:eventCode", namespaces=self._ns)
        assert all(
            [
                ec.findtext(self._nstag("valueName")) == self._SUPPORTED_CAP_CP_EVENT
                for ec in eventCodes
            ]
        ), "Unsupported CAP-CP Event version"
        return eventCodes[0].findtext(self._nstag("value"))

    def __repr__(self) -> str:
        type_ = type(self)
        return f"<{type_.__qualname__}({self.__dict__})>"

    def _nstag(self, tag: str):
        """A helper to make things more readable when lxml won't let us use ns prefixes"""
        return f"{{{self._CAPNS}}}{tag}"
