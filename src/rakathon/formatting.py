"""Česká formátovací pomůcka pro deterministické textové šablony (bez I/O, bez Streamlitu)."""

from __future__ import annotations

import math


def _is_missing(x) -> bool:
    try:
        return x is None or (isinstance(x, float) and math.isnan(x)) or x != x  # noqa: PLR0124
    except (TypeError, ValueError):
        return False


def fmt_num(x, digits: int = 1) -> str:
    if _is_missing(x):
        return "–"
    x = float(x)
    if abs(x - round(x)) < 1e-9:
        return f"{int(round(x)):,}".replace(",", " ")
    return f"{x:,.{digits}f}".replace(",", " ").replace(".", ",")


def days_word(x) -> str:
    if _is_missing(x):
        return "dní"
    x = float(x)
    if abs(x - round(x)) > 1e-9:
        return "dne"
    n = abs(int(round(x)))
    if n == 1:
        return "den"
    if 2 <= n <= 4:
        return "dny"
    return "dní"


def fmt_days(x, digits: int = 1) -> str:
    if _is_missing(x):
        return "–"
    return f"{fmt_num(x, digits)} {days_word(x)}"


def fmt_signed_days(x, digits: int = 1) -> str:
    if _is_missing(x):
        return "–"
    sign = "+" if float(x) > 0 else ("−" if float(x) < 0 else "±")
    return f"{sign}{fmt_num(abs(float(x)), digits)} {days_word(x)}"


def fmt_signed(x, digits: int = 1) -> str:
    if _is_missing(x):
        return "–"
    sign = "+" if float(x) > 0 else ("−" if float(x) < 0 else "±")
    return f"{sign}{fmt_num(abs(float(x)), digits)}"


def fmt_pct(x, digits: int = 0) -> str:
    if _is_missing(x):
        return "–"
    return f"{fmt_num(100 * float(x), digits)} %"


def fmt_pp(x) -> str:
    if _is_missing(x):
        return "–"
    return f"{fmt_signed(100 * float(x), 0)} p. b."


def patients_word(n: int) -> str:
    n = abs(int(n))
    if n == 1:
        return "pacient"
    if 2 <= n <= 4:
        return "pacienti"
    return "pacientů"


def stays_word(n: int) -> str:
    n = abs(int(n))
    if n == 1:
        return "pobyt"
    if 2 <= n <= 4:
        return "pobyty"
    return "pobytů"
