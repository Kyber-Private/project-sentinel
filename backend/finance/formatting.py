"""Currency and number formatting used across services and reports."""
from __future__ import annotations

from typing import Optional

SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "CAD": "CA$", "AUD": "A$"}


def money(value: Optional[float], currency: Optional[str] = "USD", signed: bool = False) -> str:
    if value is None:
        return "n/a"
    symbol = SYMBOLS.get(currency or "", "")
    sign = ""
    if value < 0:
        sign = "-"
    elif signed and value > 0:
        sign = "+"
    text = f"{abs(value):,.0f}"
    if symbol:
        return f"{sign}{symbol}{text}"
    return f"{sign}{text} {currency}" if currency else f"{sign}{text}"


def pct(value: Optional[float], signed: bool = True, digits: int = 1) -> str:
    if value is None:
        return "n/a"
    fmt = f"{{:{'+' if signed else ''}.{digits}f}}%"
    return fmt.format(value)


def month_label(period: Optional[str]) -> str:
    if not period:
        return "n/a"
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    try:
        y, m = int(period[:4]), int(period[5:7])
        return f"{names[m-1]} {y}"
    except (ValueError, IndexError):
        return period
