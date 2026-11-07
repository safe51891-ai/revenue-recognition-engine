import json
from decimal import Decimal

import httpx
import pytest

from app.extract import ExtractionError, OpenAIConfig, extract_with_openai, parse_contract_text

TEXT = (
    "Contract: C-1001\nCustomer: Acme Corp\nTransaction price: 120000.00\n"
    "Obligation: SaaS subscription | 90000 | over_time | 2026-01-01 | 2026-12-31\n"
    "Obligation: Onboarding | 10000 | point_in_time | 2026-02-15"
)
CONFIG = OpenAIConfig(api_key="sk-test")


def fake_transport(content, seen=None):
    body = content if isinstance(content, str) else json.dumps(content)

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": body}}]})

    return httpx.MockTransport(handler)


GOOD_LLM = {
    "contract_id": "C-1001",
    "customer": "Acme Corp",
    "transaction_price": "120000.00",
    "obligations": [
        {"name": "SaaS subscription", "standalone_price": "90000", "method": "over_time",
         "start": "2026-01-01", "end": "2026-12-31", "delivery_date": None},
        {"name": "Onboarding", "standalone_price": "10000", "method": "point_in_time",
         "start": None, "end": None, "delivery_date": "2026-02-15"},
    ],
}


def test_parser_reads_text_format():
    c = parse_contract_text(TEXT)
    assert c.contract_id == "C-1001"
    assert c.transaction_price == Decimal("120000.00")
    assert [p.name for p in c.obligations] == ["SaaS subscription", "Onboarding"]


def test_parser_reports_missing_field():
    with pytest.raises(ExtractionError, match="missing field: customer"):
        parse_contract_text("Contract: C-1\nTransaction price: 10\nObligation: A | 10 | point_in_time | 2026-01-01")


def test_parser_reports_bad_method():
    with pytest.raises(ExtractionError, match="over_time"):
        parse_contract_text("Contract: C-1\nCustomer: X\nTransaction price: 10\nObligation: A | 10 | sometime | 2026-01-01")


def test_llm_answer_becomes_contract_when_prices_appear_in_text():
    c = extract_with_openai(TEXT, CONFIG, transport=fake_transport(GOOD_LLM))
    assert c.transaction_price == Decimal("120000.00")
    assert len(c.obligations) == 2


def test_llm_price_not_in_source_is_rejected():
    wrong = {**GOOD_LLM, "transaction_price": "130000.00"}
    with pytest.raises(ExtractionError, match="does not appear in the contract text"):
        extract_with_openai(TEXT, CONFIG, transport=fake_transport(wrong))


def test_llm_error_answer_is_extraction_error():
    with pytest.raises(ExtractionError, match="no contract date"):
        extract_with_openai(TEXT, CONFIG, transport=fake_transport({"error": "no contract date"}))


def test_llm_request_sends_key_as_bearer_and_uses_json_mode():
    seen: list[httpx.Request] = []
    extract_with_openai(TEXT, CONFIG, transport=fake_transport(GOOD_LLM, seen=seen))
    body = json.loads(seen[0].content)
    assert seen[0].headers["authorization"] == "Bearer sk-test"
    assert body["response_format"] == {"type": "json_object"}
    assert body["model"] == "gpt-6-luna"
