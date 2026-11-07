"""Turn contract text into a Contract. Two ways:

- parse_contract_text: rule-based, reads the "Field: value" format in data/.
- extract_with_openai: an LLM only extracts the terms. It never does the arithmetic.
  Its output is validated with Pydantic and the same engine checks as the parser.

Text format:
  Contract: C-1001
  Customer: Acme Corp
  Transaction price: 120000.00
  Obligation: SaaS subscription | 90000 | over_time | 2026-01-01 | 2026-12-31
  Obligation: Onboarding | 10000 | point_in_time | 2026-02-15
"""
import json
import os
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx
from pydantic import ValidationError

from .models import Contract, PerformanceObligation

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_OPENAI_MODEL = "gpt-6-luna"

SYSTEM_PROMPT = """Extract contract terms from the text. Return only a JSON object:
{"contract_id": str, "customer": str, "transaction_price": "decimal string",
 "obligations": [{"name": str, "standalone_price": "decimal string",
                  "method": "over_time" or "point_in_time",
                  "start": "YYYY-MM-DD or null", "end": "YYYY-MM-DD or null",
                  "delivery_date": "YYYY-MM-DD or null"}]}
Copy values exactly from the text. Do not compute anything. If a value is missing, return
{"error": "<short reason>"}."""


class ExtractionError(ValueError):
    """The text or the model answer could not be turned into a usable contract."""


class LLMError(RuntimeError):
    """The model call failed."""


def _parse_date(raw: str, field: str) -> date:
    try:
        return date.fromisoformat(raw.strip())
    except ValueError as exc:
        raise ExtractionError(f"invalid date '{raw.strip()}' in {field}") from exc


def _parse_money(raw: str, field: str) -> Decimal:
    try:
        return Decimal(raw.strip().replace(",", ""))
    except InvalidOperation as exc:
        raise ExtractionError(f"cannot read amount '{raw.strip()}' in {field}") from exc


def parse_contract_text(text: str) -> Contract:
    fields: dict[str, str] = {}
    obligations: list[PerformanceObligation] = []

    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        if key == "obligation":
            parts = [p.strip() for p in value.split("|")]
            if len(parts) < 3:
                raise ExtractionError(f"obligation line needs name | price | method: '{value.strip()}'")
            name, price, method = parts[0], parts[1], parts[2]
            try:
                po = PerformanceObligation(
                    name=name,
                    standalone_price=_parse_money(price, f"obligation '{name}'"),
                    method=method,
                    start=_parse_date(parts[3], name) if method == "over_time" and len(parts) > 3 else None,
                    end=_parse_date(parts[4], name) if method == "over_time" and len(parts) > 4 else None,
                    delivery_date=_parse_date(parts[3], name) if method == "point_in_time" and len(parts) > 3 else None,
                )
            except ValidationError as exc:
                raise ExtractionError(f"obligation '{name}': {exc.errors()[0]['msg']}") from exc
            obligations.append(po)
        else:
            fields.setdefault(key, value.strip())

    for required in ("contract", "customer", "transaction price"):
        if required not in fields:
            raise ExtractionError(f"missing field: {required}")
    if not obligations:
        raise ExtractionError("no obligation lines found")

    try:
        return Contract(
            contract_id=fields["contract"],
            customer=fields["customer"],
            transaction_price=_parse_money(fields["transaction price"], "transaction price"),
            obligations=obligations,
        )
    except ValidationError as exc:
        raise ExtractionError(str(exc.errors()[0]["msg"])) from exc


@dataclass(frozen=True)
class OpenAIConfig:
    api_key: str
    model: str = DEFAULT_OPENAI_MODEL


def openai_config_from_env() -> OpenAIConfig | None:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        return None
    return OpenAIConfig(api_key=key, model=os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip())


def _call_openai(text: str, config: OpenAIConfig, transport: httpx.BaseTransport | None) -> dict:
    body = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        "response_format": {"type": "json_object"},
        "reasoning_effort": "none",
    }
    try:
        with httpx.Client(timeout=30, transport=transport) as client:
            response = client.post(OPENAI_URL, headers={"Authorization": f"Bearer {config.api_key}"}, json=body)
    except httpx.HTTPError as exc:
        raise LLMError(f"could not reach OpenAI: {exc.__class__.__name__}") from exc
    if response.status_code >= 400:
        raise LLMError(f"OpenAI returned HTTP {response.status_code}")
    try:
        return json.loads(response.json()["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise LLMError("OpenAI returned an unexpected response") from exc


def extract_with_openai(
    text: str,
    config: OpenAIConfig,
    transport: httpx.BaseTransport | None = None,
) -> Contract:
    """LLM extraction with guardrails: every price in the answer must appear in the source text."""
    data = _call_openai(text, config, transport)
    if "error" in data:
        raise ExtractionError(str(data["error"]))

    source_numbers = {
        Decimal(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)
    }
    try:
        contract = Contract.model_validate(
            {
                "contract_id": data.get("contract_id", ""),
                "customer": data.get("customer", ""),
                "transaction_price": data.get("transaction_price", "0"),
                "obligations": data.get("obligations", []),
            }
        )
    except ValidationError as exc:
        raise ExtractionError(f"model answer invalid: {exc.errors()[0]['msg']}") from exc

    if contract.transaction_price not in source_numbers:
        raise ExtractionError(f"transaction price {contract.transaction_price} does not appear in the contract text")
    for po in contract.obligations:
        if po.standalone_price not in source_numbers:
            raise ExtractionError(f"price {po.standalone_price} for '{po.name}' does not appear in the contract text")
    return contract
