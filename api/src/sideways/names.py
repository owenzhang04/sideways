"""Artist-name normalization, used to merge artists across services that share no IDs."""

import re
import unicodedata

_PUNCT = re.compile(r"[^\w\s]")
_SPACE = re.compile(r"\s+")


def norm_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode() or name
    text = text.casefold().replace("&", " and ")
    text = _SPACE.sub(" ", _PUNCT.sub(" ", text)).strip()
    if text.startswith("the "):
        text = text[4:]
    return text
