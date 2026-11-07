"""Run the synthetic contracts through the parser and engine and print a PASS/FAIL report.

Usage: python scripts/evaluate.py
A case passes when:
  - expect "ok": the contract parses, the schedule balances, and the checked monthly totals match.
  - expect "invalid": parsing or the engine rejects it.
"""
import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.engine import ScheduleError, schedule  # noqa: E402
from app.extract import ExtractionError, parse_contract_text  # noqa: E402


def outcome(text: str, expected_totals: dict[str, str] | None) -> tuple[str, str, bool]:
    """Return (actual, detail, totals_match)."""
    try:
        contract = parse_contract_text(text)
        frame = schedule(contract)
    except (ExtractionError, ScheduleError) as exc:
        return "invalid", str(exc), True

    by_period = frame.groupby("period")["amount"].sum()
    totals = {period: str(Decimal(str(value)).quantize(Decimal("0.01"))) for period, value in by_period.items()}
    detail = f"{len(frame)} rows, total {sum(Decimal(str(v)) for v in frame['amount']):.2f}"
    match = True
    if expected_totals is not None:
        match = all(totals.get(p) == v for p, v in expected_totals.items())
    return "ok", detail, match


def main() -> int:
    cases = json.loads((ROOT / "data" / "synthetic_contracts.json").read_text())
    correct = 0
    print(f"{'id':8} {'expected':9} {'actual':9} {'result':6} detail")
    for case in cases:
        actual, detail, totals_match = outcome(case["text"], case.get("expect_total_by_period"))
        ok = actual == case["expect"] and totals_match
        correct += ok
        print(f"{case['id']:8} {case['expect']:9} {actual:9} {'PASS' if ok else 'FAIL':6} {detail}")
    print(f"\nAccuracy: {correct}/{len(cases)} = {correct / len(cases):.0%}")
    return 0 if correct == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
