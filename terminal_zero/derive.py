"""Versioned derivations — the only way a computed number may enter a brief.

The rule: the model never does arithmetic on the data. Any figure that isn't
quoted directly from a source is produced by one of these named, versioned
functions, applied to observation values. That keeps every computed number
reproducible and auditable — you can re-run the exact function on the exact
inputs and get the exact figure.

Each derivation carries a version so a brief can record *which* calculation
produced a number. Guards raise rather than coerce (no silent divide-by-zero).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Derivation:
    name: str
    version: str
    unit: str
    doc: str
    fn: Callable


def _ratio(numerator: float, denominator: float) -> float:
    if denominator == 0:
        raise ValueError("division by zero in ratio derivation")
    return numerator / denominator


def _cagr(first: float, last: float, years: float) -> float:
    """Compound annual growth rate over `years` periods."""
    if first <= 0 or years <= 0:
        raise ValueError(f"cagr needs first>0 and years>0 (got first={first}, years={years})")
    return (last / first) ** (1.0 / years) - 1.0


def _yoy(previous: float, current: float) -> float:
    if previous == 0:
        raise ValueError("year-over-year change undefined when previous is 0")
    return (current - previous) / previous


def _index_to_base(series: list[float], base: float) -> list[float]:
    if base == 0:
        raise ValueError("cannot index to a base of 0")
    return [v / base * 100.0 for v in series]


# The registry. Add a calculation here (with a version) rather than inlining
# arithmetic anywhere else.
DERIVATIONS: dict[str, Derivation] = {
    "ratio": Derivation(
        "ratio", "1.0.0", "ratio",
        "numerator / denominator (generic share or multiple)", _ratio),
    "avg_annual_pay": Derivation(
        "avg_annual_pay", "1.0.0", "USD per worker",
        "total_annual_wages / annual_avg_emplvl", _ratio),
    "avg_establishment_size": Derivation(
        "avg_establishment_size", "1.0.0", "workers per establishment",
        "annual_avg_emplvl / annual_avg_estabs", _ratio),
    "cagr": Derivation(
        "cagr", "1.0.0", "fraction per year",
        "(last/first)^(1/years) - 1", _cagr),
    "yoy": Derivation(
        "yoy", "1.0.0", "fraction",
        "(current - previous) / previous", _yoy),
    "index_to_base": Derivation(
        "index_to_base", "1.0.0", "index (base = 100)",
        "each value / base * 100", _index_to_base),
}


def apply(name: str, *args):
    """Apply a named derivation. Raises KeyError if the name isn't registered."""
    if name not in DERIVATIONS:
        raise KeyError(f"unknown derivation {name!r}; registered: {sorted(DERIVATIONS)}")
    return DERIVATIONS[name].fn(*args)


def version(name: str) -> str:
    return DERIVATIONS[name].version
