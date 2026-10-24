from xml.etree.ElementTree import ParseError

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring


def detect_media_type(content: bytes) -> str | None:
    if content.startswith(b"%PDF-"):
        return "application/pdf"

    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"

    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"

    xml_content = content.lstrip(b"\xef\xbb\xbf \t\r\n")

    if xml_content.startswith(b"<"):
        try:
            fromstring(content)
        except (ParseError, DefusedXmlException):
            return None

        return "application/xml"

    return None