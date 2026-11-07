"""ASC 606-style revenue schedule, calculated in plain code with Decimal.

Steps implemented:
  1. Contract identified (the input is a contract with a price and obligations).
  2. Performance obligations listed (each has a standalone selling price and a method).
  3. Transaction price allocated by relative standalone selling price.
  4. Revenue recognised monthly: straight-line over time, or in one month at delivery.

No model is used here. An LLM may only extract terms (see extract.py), and every
schedule is checked against the transaction price before it is returned.
"""
from datetime import date
from decimal import ROUND_DOWN, Decimal

import pandas as pd

from .models import Contract, PerformanceObligation, ScheduleRow

CENT = Decimal("0.01")


class ScheduleError(ValueError):
    """Contract terms are invalid, so no schedule can be produced."""


def _month_index(d: date) -> int:
    return d.year * 12 + (d.month - 1)


def _label(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def validate(contract: Contract) -> list[str]:
    """Return human-readable problems. An empty list means the terms are usable."""
    issues: list[str] = []
    for po in contract.obligations:
        if po.method == "over_time":
            if po.start is None or po.end is None:
                issues.append(f"'{po.name}': over_time needs start and end dates")
            elif po.end < po.start:
                issues.append(f"'{po.name}': end date is before start date")
        else:
            if po.delivery_date is None:
                issues.append(f"'{po.name}': point_in_time needs a delivery date")

    names = [po.name for po in contract.obligations]
    if len(set(names)) != len(names):
        issues.append("duplicate performance obligation names")

    total_ssp = sum(po.standalone_price for po in contract.obligations)
    if total_ssp == 0:
        issues.append("standalone prices sum to zero")
    return issues


def allocate(contract: Contract) -> dict[str, Decimal]:
    """Allocate the transaction price by relative standalone selling price (ASC 606-10-32-31).

    Each share is rounded down to the cent. The rounding remainder goes to the
    obligation with the largest standalone price, so allocations sum exactly.
    """
    issues = validate(contract)
    if issues:
        raise ScheduleError("; ".join(issues))

    total_ssp = sum(po.standalone_price for po in contract.obligations)
    shares = {
        po.name: (contract.transaction_price * po.standalone_price / total_ssp).quantize(CENT, rounding=ROUND_DOWN)
        for po in contract.obligations
    }
    remainder = contract.transaction_price - sum(shares.values())
    largest = max(contract.obligations, key=lambda po: po.standalone_price)
    shares[largest.name] += remainder
    return shares


def _spread(total: Decimal, months: list[int]) -> list[Decimal]:
    """Split total evenly across months in cents. The last month takes the remainder."""
    base = (total / len(months)).quantize(CENT, rounding=ROUND_DOWN)
    amounts = [base] * len(months)
    amounts[-1] += total - base * len(months)
    return amounts


def _rows_for(contract_id: str, po: PerformanceObligation, amount: Decimal) -> list[ScheduleRow]:
    if po.method == "point_in_time":
        assert po.delivery_date is not None
        return [ScheduleRow(contract_id=contract_id, obligation=po.name,
                            period=_label(_month_index(po.delivery_date)), amount=amount)]

    assert po.start is not None and po.end is not None
    months = list(range(_month_index(po.start), _month_index(po.end) + 1))
    return [
        ScheduleRow(contract_id=contract_id, obligation=po.name, period=_label(m), amount=a)
        for m, a in zip(months, _spread(amount, months))
    ]


def schedule(contract: Contract) -> pd.DataFrame:
    """Return the monthly revenue schedule. Raises ScheduleError if it cannot be checked."""
    allocations = allocate(contract)
    rows: list[ScheduleRow] = []
    for po in contract.obligations:
        rows.extend(_rows_for(contract.contract_id, po, allocations[po.name]))

    total = sum((r.amount for r in rows), Decimal("0"))
    if total != contract.transaction_price:
        raise ScheduleError(f"schedule total {total} does not equal transaction price {contract.transaction_price}")

    frame = pd.DataFrame([r.model_dump() for r in rows])
    return frame.groupby(["contract_id", "period", "obligation"], as_index=False)["amount"].sum().sort_values(["period", "obligation"]).reset_index(drop=True)
