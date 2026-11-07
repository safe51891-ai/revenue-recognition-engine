# Revenue Recognition Engine (ASC 606 style)

Turns a customer contract into a month-by-month revenue schedule.

The schedule is calculated in plain code with `Decimal`. An LLM can extract the contract terms from text, but it never does the arithmetic, and every schedule is checked before it is returned. The point of the project is knowing which parts should not be AI.

## What it does

1. **Identify the contract:** ID, customer, transaction price.
2. **List performance obligations:** each has a standalone selling price and a recognition method.
3. **Allocate the transaction price** by relative standalone selling price, as ASC 606-10-32-31 requires. Shares are rounded down to the cent and the remainder goes to the largest obligation, so the allocations add up exactly.
4. **Recognise revenue monthly:**
   - `over_time`: straight-line from the start month to the end month, inclusive. Cent remainders go to the last month.
   - `point_in_time`: all of that obligation's revenue in the delivery month.
5. **Check the result:** the schedule total must equal the transaction price, or nothing is returned.

## Input format

```
Contract: C-1001
Customer: Acme Corp
Transaction price: 120000.00
Obligation: SaaS subscription | 90000 | over_time | 2026-01-01 | 2026-12-31
Obligation: Onboarding | 10000 | point_in_time | 2026-02-15
```

- `Obligation` lines are `name | standalone price | method | dates`.
- `over_time` takes a start date and an end date. `point_in_time` takes a delivery date.
- Dates are `YYYY-MM-DD`.

## Output

A pandas DataFrame with one row per contract, period (`YYYY-MM`) and obligation:

| contract_id | period | obligation | amount |
|---|---|---|---|
| C-1001 | 2026-01 | SaaS subscription | 9000.00 |
| C-1001 | 2026-02 | Onboarding | 10000.00 |
| C-1001 | 2026-02 | SaaS subscription | 9000.00 |

## Optional LLM extraction

`app/extract.py` can also read free-form contract text with an LLM (OpenAI, `OPENAI_API_KEY`, default model `gpt-6-luna`). The model only copies terms. Guardrails:

- Every price in its answer must appear in the source text.
- The answer is validated with Pydantic, then goes through the same engine checks as the parser.

The LLM path is covered by mock tests only. It has not been run live in this repo.

## Run it

```bash
python3.13 -m venv .venv && source .venv/bin/activate   # Python 3.10+
pip install -r requirements.txt
python -m pytest -q
python scripts/evaluate.py
```

## Evaluation

`data/synthetic_contracts.json` has 8 invented contracts. `scripts/evaluate.py` runs each one through the parser and engine. A case passes when:

- For `ok` cases: the contract parses, the schedule balances, and the checked monthly totals match.
- For `invalid` cases: the parser or engine rejects the contract.

| Cases | Expected outcome |
|---|---|
| RR-001 to 004: valid contracts, including rounding and a point-in-time obligation | ok, totals checked |
| RR-005: end date before start date | invalid |
| RR-006: unknown recognition method | invalid |
| RR-007: impossible date (month 13) | invalid |
| RR-008: missing transaction price | invalid |

**Result:** 8 of 8 (100%). Tests: 15 passing (`pytest`). These numbers come from synthetic cases I wrote, so they show the rules work as designed, not how the engine performs on real contracts.

## What AI does not do here

- It does not compute any amount, allocation or schedule.
- It does not decide a recognition method. The method must be stated in the contract terms.
- It does not approve anything. An LLM-extracted contract still has to pass every engine check.

## Structure

```
app/
  models.py    Contract, PerformanceObligation, ScheduleRow (Decimal money)
  engine.py    validation, SSP allocation, monthly schedule, total check
  extract.py   rule-based parser; optional LLM extraction with guardrails
data/          synthetic contracts with expected outcomes
scripts/evaluate.py  PASS/FAIL report
tests/         pytest suite
```

## Limits

- Only the two recognition patterns above are supported. Variable consideration, contract modifications, and multi-element bundles with price changes are not modelled.
- Standalone selling prices are supplied, not estimated.
- Results are in memory only; there is no database.

## Note

All sample data is synthetic. Customers, prices and dates are invented.
