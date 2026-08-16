from __future__ import annotations
import re
from dataclasses import dataclass
@dataclass(frozen=True)
class TextToken:
    start:int
    end:int
    raw:bytes
def text_tokens(xml:bytes)->list[TextToken]:
    return [TextToken(m.start(1),m.end(1),m.group(1)) for m in re.finditer(rb'<(?:[A-Za-z_][\w.-]*:)?t(?:\s[^>]*)?>(.*?)</(?:[A-Za-z_][\w.-]*:)?t\s*>',xml,re.S)]
