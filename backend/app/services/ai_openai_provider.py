import json
from typing import Any

import httpx

from app.domain.models import AiDecision, SignalAction, StrategySignal

AI_DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "confidence", "strategy", "reasons", "risk_flags"],
    "properties": {
        "action": {"type": "string", "enum": ["LONG", "SHORT", "NO_TRADE"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "strategy": {"type": "string"},
        "reasons": {
            "type": "array",
            "maxItems": 4,
            "items": {"type": "string"},
        },
        "risk_flags": {
            "type": "array",
            "maxItems": 6,
            "items": {"type": "string"},
        },
    },
}


class OpenAiSignalEvaluator:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 3.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def evaluate(self, signal: StrategySignal) -> AiDecision:
        payload = self._build_payload(signal)
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/responses",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        response.raise_for_status()
        return AiDecision.model_validate_json(self._extract_output_text(response.json()))

    def _build_payload(self, signal: StrategySignal) -> dict[str, Any]:
        signal_payload = signal.model_dump(mode="json")
        return {
            "model": self.model,
            "store": False,
            "input": [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "You are a conservative futures trade filter. "
                                "You cannot place orders, increase risk, increase leverage, "
                                "or reverse the scanner direction. Only approve the same "
                                "direction or return NO_TRADE. Reject unclear, overextended, "
                                "low-liquidity, high-volatility, stale, or poor RR setups. "
                                "Prefer capital preservation over missed trades."
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": json.dumps(
                                {
                                    "allowed_actions": [
                                        SignalAction.LONG.value
                                        if signal.side.value == "LONG"
                                        else SignalAction.SHORT.value,
                                        SignalAction.NO_TRADE.value,
                                    ],
                                    "signal": signal_payload,
                                    "decision_policy": {
                                        "approve_only_if_same_direction": True,
                                        "reject_if_confidence_below": 0.65,
                                        "reject_if_reasons_conflict": True,
                                        "never_increase_risk": True,
                                    },
                                },
                                separators=(",", ":"),
                            ),
                        }
                    ],
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "ai_trade_filter_decision",
                    "strict": True,
                    "schema": AI_DECISION_SCHEMA,
                }
            },
        }

    @staticmethod
    def _extract_output_text(payload: dict[str, Any]) -> str:
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text
        for output in payload.get("output", []):
            if not isinstance(output, dict):
                continue
            for content in output.get("content", []):
                if not isinstance(content, dict):
                    continue
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    return text
        raise ValueError("OpenAI response missing output text")
