"""Independent, fail-closed Haiku evaluator.

No execution, order, exchange, or risk imports are allowed here. Results are
telemetry only and are intentionally never returned to the trading path.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

import httpx


@dataclass(frozen=True)
class ShadowEvaluation:
    status: str
    provider: str
    model: str
    verdict: str | None = None
    confidence: float | None = None
    rationale: str | None = None
    error: str | None = None
    shadow_only: bool = True

    def as_log_payload(self) -> dict[str, object]:
        return {
            "status": self.status,
            "provider": self.provider,
            "model": self.model,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "error": self.error,
            "shadow_only": True,
            "execution_enabled": False,
        }


class AnthropicHaikuProvider:
    def __init__(self, *, api_key: str, base_url: str, model: str, timeout_seconds: float) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def evaluate(self, evidence: dict[str, Any]) -> ShadowEvaluation:
        if not self.api_key:
            return ShadowEvaluation(
                "FAIL_CLOSED", "anthropic", self.model, error="missing_credential"
            )
        payload = {
            "model": self.model,
            "max_tokens": 256,
            "temperature": 0,
            "system": "Return JSON only: verdict BUY, SELL, SKIP, or UNKNOWN; confidence 0..1; rationale. This is shadow analysis, never execution.",
            "messages": [{"role": "user", "content": json.dumps(evidence, separators=(",", ":"))}],
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/v1/messages",
                    headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
                    json=payload,
                )
                response.raise_for_status()
                body = response.json()
            text = next(
                block["text"] for block in body.get("content", []) if block.get("type") == "text"
            )
            parsed = self._parse_json_object(text)
            verdict = parsed.get("verdict")
            confidence = parsed.get("confidence")
            rationale = parsed.get("rationale")
            if verdict not in {"BUY", "SELL", "SKIP", "UNKNOWN"}:
                raise ValueError("invalid_verdict")
            if (
                isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or not 0 <= float(confidence) <= 1
            ):
                raise ValueError("invalid_confidence")
            if not isinstance(rationale, str):
                raise TypeError("invalid_rationale")
            return ShadowEvaluation(
                "OK", "anthropic", self.model, verdict, float(confidence), rationale[:1000]
            )
        except (TimeoutError, httpx.TimeoutException):
            return ShadowEvaluation("FAIL_CLOSED", "anthropic", self.model, error="timeout")
        except (
            httpx.HTTPError,
            json.JSONDecodeError,
            AttributeError,
            KeyError,
            StopIteration,
            TypeError,
            ValueError,
        ):
            return ShadowEvaluation(
                "FAIL_CLOSED", "anthropic", self.model, error="provider_or_parse_error"
            )
        except Exception:  # noqa: BLE001 - provider failures must never escape shadow mode
            return ShadowEvaluation(
                "FAIL_CLOSED", "anthropic", self.model, error="unexpected_provider_error"
            )

    @staticmethod
    def _parse_json_object(text: str) -> dict[str, Any]:
        if not isinstance(text, str):
            raise TypeError("invalid_text_block")
        candidate = text.strip()
        if candidate.startswith("```"):
            lines = candidate.splitlines()
            if (
                len(lines) < 3
                or lines[0].lower() not in {"```", "```json"}
                or lines[-1].strip() != "```"
            ):
                raise ValueError("invalid_json_fence")
            candidate = "\n".join(lines[1:-1]).strip()
        parsed = json.loads(candidate)
        if not isinstance(parsed, dict):
            raise TypeError("invalid_json_object")
        return parsed


class AIShadowEvaluator:
    def __init__(self, app_state: Any) -> None:
        self.state = app_state

    async def evaluate(self, scanner_result: Any) -> ShadowEvaluation:
        config = self.state.ai_shadow_config
        model = str(config["model"])
        if not config.get("enabled", False):
            return ShadowEvaluation("DISABLED", "anthropic", model)
        provider = AnthropicHaikuProvider(
            api_key=self.state.settings.anthropic_api_key,
            base_url=self.state.settings.anthropic_base_url,
            model=model,
            timeout_seconds=self.state.settings.ai_evaluator_timeout_seconds,
        )
        evidence = {
            "symbol": scanner_result.symbol,
            "timeframe": scanner_result.timeframe.value,
            "action": scanner_result.action.value,
            "price": scanner_result.price,
            "scores": {"long": scanner_result.long_score, "short": scanner_result.short_score},
            "risk_reward": scanner_result.risk_reward,
            "regime": scanner_result.regime.value,
            "shadow_only": True,
        }
        return await provider.evaluate(evidence)

    async def evaluate_and_log(self, scanner_result: Any) -> None:
        started = perf_counter()
        result = await self.evaluate(scanner_result)
        latency_ms = round((perf_counter() - started) * 1000, 3)
        scanned_at = scanner_result.scanned_at.isoformat()
        correlation_source = (
            f"{scanner_result.symbol}|{scanner_result.timeframe.value}|"
            f"{scanner_result.action.value}|{scanned_at}"
        )
        telemetry = {
            **result.as_log_payload(),
            "correlation_id": hashlib.sha256(correlation_source.encode()).hexdigest()[:20],
            "evaluated_at": datetime.now(UTC).isoformat(),
            "latency_ms": latency_ms,
            "symbol": scanner_result.symbol,
            "timeframe": scanner_result.timeframe.value,
            "baseline_action": scanner_result.action.value,
            "baseline_long_score": scanner_result.long_score,
            "baseline_short_score": scanner_result.short_score,
            "baseline_regime": scanner_result.regime.value,
            "baseline_strategy": scanner_result.strategy,
        }
        await self.state.storage.log(
            "AI Haiku shadow evaluation",
            telemetry,
            level="INFO" if result.status in {"OK", "DISABLED"} else "WARNING",
        )
