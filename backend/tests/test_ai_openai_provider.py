from app.domain.models import Side, StrategySignal
from app.services.ai_openai_provider import OpenAiSignalEvaluator


def make_signal(**overrides):
    data = {
        "symbol": "BTCUSDT",
        "side": Side.LONG,
        "confidence": 0.82,
        "entry_price": 100.0,
        "stop_loss": 98.0,
        "take_profit": 105.0,
        "take_profits": [102.0, 104.0, 105.0],
        "leverage": 5,
        "risk_fraction": 0.005,
    }
    data.update(overrides)
    return StrategySignal(**data)


def test_openai_payload_uses_strict_structured_output():
    provider = OpenAiSignalEvaluator(api_key="test", model="gpt-test")
    payload = provider._build_payload(make_signal())

    assert payload["model"] == "gpt-test"
    assert payload["store"] is False
    assert payload["text"]["format"]["type"] == "json_schema"
    assert payload["text"]["format"]["strict"] is True
    assert payload["text"]["format"]["schema"]["properties"]["action"]["enum"] == [
        "LONG",
        "SHORT",
        "NO_TRADE",
    ]


def test_extract_output_text_supports_output_text_shortcut():
    text = '{"action":"NO_TRADE","confidence":0,"strategy":"scanner","reasons":[],"risk_flags":[]}'

    assert OpenAiSignalEvaluator._extract_output_text({"output_text": text}) == text


def test_extract_output_text_supports_responses_output_items():
    text = '{"action":"LONG","confidence":0.7,"strategy":"scanner","reasons":[],"risk_flags":[]}'
    payload = {"output": [{"content": [{"type": "output_text", "text": text}]}]}

    assert OpenAiSignalEvaluator._extract_output_text(payload) == text
