"""Conservative normalization with explicit decimal convention and exact decimal arithmetic."""
from decimal import Decimal
import re


def amount(text: str, decimal_separator=".") -> tuple[str, str | None] | None:
    grouping = "," if decimal_separator == "." else "."
    match = re.fullmatch(r"\s*([$€£])?\s*([0-9.,]+)\s*([kKmM])?\s*(BB)?\s*", text)
    if not match or (match[1] and match[4]):
        return None
    integer = rf"(?:[0-9]+|[0-9]{{1,3}}(?:{re.escape(grouping)}[0-9]{{3}})+)"
    if not re.fullmatch(integer + rf"(?:{re.escape(decimal_separator)}[0-9]{{1,2}})?", match[2]):
        return None
    number = Decimal(match[2].replace(grouping, "").replace(decimal_separator, "."))
    multiplier = {"k": 1000, "m": 1000000}.get((match[3] or "").lower(), 1)
    number *= multiplier
    if number > Decimal("1000000000000"):
        return None
    value = format(number, "f")
    if "." in value:
        value = value.rstrip("0").rstrip(".")
    return value, match[1] or match[4]


def parse(text: str, kind: str, decimal_separator="."):
    text = text.strip()
    if kind == "nickname":
        return (text, None) if re.fullmatch(r"[\w.-]{1,32}", text) else None
    if kind == "amount":
        return amount(text, decimal_separator)
    if kind == "blinds":
        parts = text.split("/")
        if len(parts) != 2:
            return None
        small, big = (amount(part, decimal_separator) for part in parts)
        if not small or not big or (small[1] and big[1] and small[1] != big[1]):
            return None
        if not 0 < Decimal(small[0]) <= Decimal(big[0]):
            return None
        return f"{small[0]} / {big[0]}", small[1] or big[1]
    return None
