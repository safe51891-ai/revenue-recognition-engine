from datetime import date
from decimal import Decimal

import pytest

from app.engine import ScheduleError, allocate, schedule, validate
from app.models import Contract, PerformanceObligation


def po(name, ssp, method="over_time", start=date(2026, 1, 1), end=date(2026, 12, 31), delivery=None):
    return PerformanceObligation(
        name=name,
        standalone_price=Decimal(ssp),
        method=method,
        start=start if method == "over_time" else None,
        end=end if method == "over_time" else None,
        delivery_date=delivery if method == "point_in_time" else None,
    )


def contract(price, *obligations):
    return Contract(contract_id="C-T", customer="Test", transaction_price=Decimal(price), obligations=list(obligations))


def test_allocation_is_by_relative_standalone_price_and_sums_exactly():
    c = contract("1000.00", po("A", "3"), po("B", "1"), po("C", "2"))
    shares = allocate(c)
    assert sum(shares.values()) == Decimal("1000.00")
    assert shares["B"] == Decimal("166.66")  # 1/6 rounded down; remainder goes to the largest obligation
    assert shares["A"] == Decimal("500.01")
    assert shares["C"] == Decimal("333.33")


def test_over_time_obligation_is_straight_line_by_month():
    c = contract("300.00", po("Support", "300", start=date(2026, 1, 1), end=date(2026, 3, 31)))
    frame = schedule(c)
    assert list(frame["period"]) == ["2026-01", "2026-02", "2026-03"]
    assert list(frame["amount"]) == [Decimal("100.00")] * 3


def test_cent_remainder_lands_in_last_month():
    c = contract("100.00", po("Support", "100", start=date(2026, 1, 1), end=date(2026, 3, 31)))
    amounts = list(schedule(c)["amount"])
    assert sum(amounts) == Decimal("100.00")
    assert amounts[-1] >= amounts[0]


def test_point_in_time_recognised_in_delivery_month():
    c = contract("500.00", po("Licence", "500", method="point_in_time", delivery=date(2026, 7, 15)))
    frame = schedule(c)
    assert list(frame["period"]) == ["2026-07"]
    assert frame["amount"].iloc[0] == Decimal("500.00")


def test_schedule_total_always_equals_transaction_price():
    c = contract("12345.67", po("A", "7"), po("B", "5", method="point_in_time", delivery=date(2026, 2, 1)))
    frame = schedule(c)
    assert sum(frame["amount"]) == Decimal("12345.67")


def test_end_before_start_is_invalid():
    c = contract("100", po("A", "100", start=date(2026, 5, 1), end=date(2026, 4, 1)))
    assert any("end date is before start date" in issue for issue in validate(c))
    with pytest.raises(ScheduleError):
        schedule(c)


def test_duplicate_obligation_names_are_invalid():
    c = contract("100", po("A", "50", method="point_in_time", delivery=date(2026, 1, 1)),
                 po("A", "50", method="point_in_time", delivery=date(2026, 2, 1)))
    assert "duplicate performance obligation names" in validate(c)


def test_single_day_over_time_period_is_one_month():
    c = contract("80.00", po("Day", "80", start=date(2026, 6, 10), end=date(2026, 6, 10)))
    frame = schedule(c)
    assert list(frame["period"]) == ["2026-06"]
    assert frame["amount"].iloc[0] == Decimal("80.00")
