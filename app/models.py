"""Contract and performance-obligation models. Money is always Decimal."""
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class PerformanceObligation(BaseModel):
    name: str = Field(min_length=1)
    standalone_price: Decimal = Field(gt=0)
    method: Literal["over_time", "point_in_time"]
    start: date | None = None  # over_time only
    end: date | None = None  # over_time only
    delivery_date: date | None = None  # point_in_time only


class Contract(BaseModel):
    contract_id: str = Field(min_length=1)
    customer: str = Field(min_length=1)
    transaction_price: Decimal = Field(gt=0)
    obligations: list[PerformanceObligation] = Field(min_length=1)


class ScheduleRow(BaseModel):
    contract_id: str
    obligation: str
    period: str  # YYYY-MM
    amount: Decimal
