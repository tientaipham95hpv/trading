import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from app.api import routes
from app.domain.models import AIShadowConfigResponse, AIShadowConfigUpdate, TradingMode
from app.services.app_state import AppState

api_app = FastAPI()
api_app.include_router(routes.router)


class FakeStorage:
    def __init__(self) -> None:
        self.logs: list[tuple[str, dict[str, object] | None, str]] = []

    async def log(
        self,
        message: str,
        payload: dict[str, object] | None = None,
        level: str = "INFO",
    ) -> None:
        self.logs.append((message, payload, level))


class FakeAIState:
    def __init__(self) -> None:
        self.ai_shadow_config = {
            "enabled": False,
            "model": "deterministic-shadow-score",
            "outcome_horizon": 24,
            "minimum_training_samples": 300,
        }
        self.trading_mode = TradingMode.DEMO
        self.storage = FakeStorage()
        self.save_count = 0

    def save_runtime_config(self) -> None:
        self.save_count += 1


def runtime_state(path: Path, *, config: dict[str, object] | None = None) -> AppState:
    state = object.__new__(AppState)
    state.trading_mode = TradingMode.DEMO
    state.live_trading_enabled = False
    state.live_preflight = {
        "all_tests_pass": False,
        "demo_stable": False,
        "sl_protection_pass": False,
        "reconnect_pass": False,
        "reconciliation_pass": False,
        "duplicate_order_tests_pass": False,
    }
    state.ai_shadow_config = config or {
        "enabled": False,
        "model": "deterministic-shadow-score",
        "outcome_horizon": 24,
        "minimum_training_samples": 300,
    }
    state.runtime_config_path = path
    state.performance_reset_at_by_mode = {TradingMode.DEMO: None, TradingMode.LIVE: None}
    state.performance_initial_capital_by_mode = {
        TradingMode.DEMO: None,
        TradingMode.LIVE: None,
    }
    return state


def training_item(index: int) -> dict[str, object]:
    event_key = f"event-{index}"
    outcomes = [
        {
            "decision_event_key": event_key,
            "horizon": horizon,
            "return_fraction": 0.01,
            "mfe_fraction": 0.02,
            "mae_fraction": -0.005,
            "decision": "WOULD_ENTER",
            "side": "LONG",
            "symbol": "BTCUSDT",
            "timeframe": "15m",
        }
        for horizon in (4, 12, 24)
    ]
    return {
        "event_key": event_key,
        "quality_score": 85,
        "outcomes": {str(row["horizon"]): row for row in outcomes},
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("outcome_horizon", 3),
        ("outcome_horizon", 97),
        ("minimum_training_samples", 49),
        ("minimum_training_samples", 10001),
    ],
)
def test_ai_shadow_update_enforces_bounds(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        AIShadowConfigUpdate(**{field: value})


def test_ai_shadow_model_is_trimmed_and_response_guardrails_are_immutable() -> None:
    update = AIShadowConfigUpdate(model="  shadow-v2  ")
    assert update.model == "shadow-v2"

    response = AIShadowConfigResponse(
        enabled=True,
        model="shadow-v2",
        outcome_horizon=24,
        minimum_training_samples=300,
    )
    assert response.mode == "SHADOW_ONLY"
    assert response.shadow_only is True
    assert response.read_only is True
    assert response.execution_enabled is False


def test_runtime_ai_shadow_config_round_trips_without_opening_live(tmp_path: Path) -> None:
    path = tmp_path / "runtime-config.json"
    original = runtime_state(
        path,
        config={
            "enabled": True,
            "model": "shadow-v2",
            "outcome_horizon": 48,
            "minimum_training_samples": 50,
        },
    )
    AppState.save_runtime_config(original)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["trading_mode"] == "DEMO"
    assert payload["live_trading_enabled"] is False
    assert payload["ai_shadow"]["model"] == "shadow-v2"
    assert payload["ai_shadow"]["outcome_horizon"] == 48

    restored = runtime_state(path)
    AppState._load_runtime_config(restored)
    assert restored.ai_shadow_config == original.ai_shadow_config
    assert restored.trading_mode == TradingMode.DEMO
    assert restored.live_trading_enabled is False


@pytest.mark.asyncio
async def test_ai_config_get_put_endpoint_is_separate_and_shadow_only(monkeypatch) -> None:
    fake_state = FakeAIState()
    monkeypatch.setattr(routes, "state", fake_state)

    transport = httpx.ASGITransport(app=api_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        before = await client.get("/api/ai/config")
        assert before.status_code == 200
        assert before.json()["mode"] == "SHADOW_ONLY"

        updated = await client.put(
            "/api/ai/config",
            json={
                "model": "  shadow-v2  ",
                "outcome_horizon": 48,
                "minimum_training_samples": 50,
                "mode": "LIVE",
                "execution_enabled": True,
            },
        )

    assert updated.status_code == 200
    body = updated.json()
    assert body["model"] == "shadow-v2"
    assert body["outcome_horizon"] == 48
    assert body["minimum_training_samples"] == 50
    assert body["mode"] == "SHADOW_ONLY"
    assert body["shadow_only"] is True
    assert body["read_only"] is True
    assert body["execution_enabled"] is False
    assert fake_state.save_count == 1
    assert fake_state.storage.logs[0][0] == "Cập nhật AI shadow config"
    assert "execution_enabled" not in fake_state.ai_shadow_config


@pytest.mark.asyncio
async def test_ai_training_uses_configured_minimum_not_execution_constant(monkeypatch) -> None:
    items = [training_item(index) for index in range(17)]  # 17 * 3 = 51 outcomes

    class TrainingStorage(FakeStorage):
        async def smart_entry_events(self, *, mode: str, limit: int) -> list[dict[str, object]]:
            assert mode == "DEMO"
            return items[:limit]

        async def smart_entry_outcomes(
            self, *, mode: str, decision_keys: list[str]
        ) -> list[dict[str, object]]:
            assert mode == "DEMO"
            return [
                outcome
                for item in items
                if item["event_key"] in decision_keys
                for outcome in item["outcomes"].values()
            ]

        async def smart_entry_collection_coverage(self, *, mode: str) -> dict[str, object]:
            return {"total_decisions": len(items), "complete_decisions": len(items)}

    fake_state = FakeAIState()
    fake_state.ai_shadow_config.update(
        {"model": "shadow-v2", "outcome_horizon": 48, "minimum_training_samples": 50}
    )
    fake_state.storage = TrainingStorage()
    fake_state.smart_entry_collector = SimpleNamespace(snapshot=lambda: {"running": False})
    monkeypatch.setattr(routes, "state", fake_state)

    result = await routes.ai_training_status(limit=50)

    assert result["model_family"] == "shadow-v2"
    assert result["configured_outcome_horizon"] == 48
    assert result["sample_size"] == 51
    assert result["minimum_sample_for_training"] == 50
    assert result["ready_for_training"] is True
    assert result["ready_for_execution"] is False
    assert result["shadow_only"] is True
    assert result["execution_enabled"] is False
    assert "AI không được đặt lệnh trực tiếp" in result["guardrails"]


class FakeHTTPResponse:
    def __init__(self, body: dict[str, object], *, status_error: bool = False) -> None:
        self.body = body
        self.status_error = status_error

    def raise_for_status(self) -> None:
        if self.status_error:
            raise httpx.HTTPStatusError("provider error", request=None, response=None)

    def json(self) -> dict[str, object]:
        return self.body


class FakeAsyncClient:
    response: FakeHTTPResponse | None = None
    error: Exception | None = None

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, *args: object, **kwargs: object) -> FakeHTTPResponse:
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


@pytest.mark.asyncio
async def test_haiku_provider_missing_credential_fails_closed_without_http(monkeypatch) -> None:
    from app.services.ai_shadow import AnthropicHaikuProvider

    async def forbidden_post(*args: object, **kwargs: object) -> None:
        raise AssertionError("HTTP must not be called without a credential")

    monkeypatch.setattr(httpx.AsyncClient, "post", forbidden_post)
    result = await AnthropicHaikuProvider(
        api_key="", base_url="https://api.anthropic.com", model="haiku", timeout_seconds=1
    ).evaluate({"symbol": "BTCUSDT"})

    assert result.status == "FAIL_CLOSED"
    assert result.error == "missing_credential"
    assert result.shadow_only is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "error", "expected_error"),
    [
        (
            FakeHTTPResponse({"content": [{"type": "text", "text": "not-json"}]}),
            None,
            "provider_or_parse_error",
        ),
        (None, httpx.ReadTimeout("slow provider"), "timeout"),
        (FakeHTTPResponse({}, status_error=True), None, "provider_or_parse_error"),
    ],
)
async def test_haiku_provider_errors_fail_closed(
    monkeypatch, response, error, expected_error
) -> None:
    from app.services.ai_shadow import AnthropicHaikuProvider

    FakeAsyncClient.response = response
    FakeAsyncClient.error = error
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    result = await AnthropicHaikuProvider(
        api_key="configured", base_url="https://api.anthropic.com", model="haiku", timeout_seconds=1
    ).evaluate({"symbol": "BTCUSDT"})

    assert result.status == "FAIL_CLOSED"
    assert result.error == expected_error
    assert result.verdict is None
    assert result.as_log_payload()["execution_enabled"] is False


@pytest.mark.asyncio
async def test_haiku_provider_accepts_only_strict_observational_json(monkeypatch) -> None:
    from app.services.ai_shadow import AnthropicHaikuProvider

    FakeAsyncClient.response = FakeHTTPResponse(
        {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"verdict": "SKIP", "confidence": 0.8, "rationale": "weak setup"}
                    ),
                }
            ]
        }
    )
    FakeAsyncClient.error = None
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    result = await AnthropicHaikuProvider(
        api_key="configured", base_url="https://api.anthropic.com", model="haiku", timeout_seconds=1
    ).evaluate({"symbol": "BTCUSDT"})

    assert result.status == "OK"
    assert result.verdict == "SKIP"
    assert result.confidence == 0.8
    assert result.shadow_only is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "expected_status"),
    [
        (
            '```json\n{"verdict":"UNKNOWN","confidence":0,"rationale":"safe"}\n```',
            "OK",
        ),
        (
            'Result: {"verdict":"UNKNOWN","confidence":0,"rationale":"safe"}',
            "FAIL_CLOSED",
        ),
        ("[]", "FAIL_CLOSED"),
    ],
)
async def test_haiku_provider_handles_only_strict_json_or_single_json_fence(
    monkeypatch, text: str, expected_status: str
) -> None:
    from app.services.ai_shadow import AnthropicHaikuProvider

    FakeAsyncClient.response = FakeHTTPResponse({"content": [{"type": "text", "text": text}]})
    FakeAsyncClient.error = None
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    result = await AnthropicHaikuProvider(
        api_key="test-key",
        base_url="https://api.anthropic.com",
        model="haiku",
        timeout_seconds=1,
    ).evaluate({"symbol": "BTCUSDT"})

    assert result.status == expected_status
    assert result.as_log_payload()["execution_enabled"] is False


@pytest.mark.asyncio
async def test_haiku_telemetry_never_contains_api_key(monkeypatch) -> None:
    from app.services.ai_shadow import AnthropicHaikuProvider

    secret = "secret-must-not-appear"
    FakeAsyncClient.response = FakeHTTPResponse(
        {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"verdict": "UNKNOWN", "confidence": 0.0, "rationale": "no edge"}
                    ),
                }
            ]
        }
    )
    FakeAsyncClient.error = None
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    result = await AnthropicHaikuProvider(
        api_key=secret,
        base_url="https://api.anthropic.com",
        model="haiku",
        timeout_seconds=1,
    ).evaluate({"symbol": "BTCUSDT"})

    assert secret not in json.dumps(result.as_log_payload())


@pytest.mark.asyncio
async def test_unexpected_provider_exception_is_still_fail_closed(monkeypatch) -> None:
    from app.services.ai_shadow import AnthropicHaikuProvider

    FakeAsyncClient.response = None
    FakeAsyncClient.error = RuntimeError("provider SDK failure")
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    result = await AnthropicHaikuProvider(
        api_key="***",
        base_url="https://api.anthropic.com",
        model="haiku",
        timeout_seconds=1,
    ).evaluate({"symbol": "BTCUSDT"})

    assert result.status == "FAIL_CLOSED"
    assert result.error == "unexpected_provider_error"
    assert result.verdict is None


@pytest.mark.asyncio
async def test_shadow_log_contains_operational_metadata_without_secret(monkeypatch) -> None:
    from datetime import UTC, datetime

    from app.services.ai_shadow import AIShadowEvaluator, ShadowEvaluation

    secret = "secret-must-not-appear"
    state = SimpleNamespace(storage=FakeStorage())
    evaluator = AIShadowEvaluator(state)

    async def fake_evaluate(scanner_result: object) -> ShadowEvaluation:
        return ShadowEvaluation(
            "OK",
            "anthropic",
            "claude-haiku-4-5",
            verdict="SKIP",
            confidence=0.75,
            rationale="observational only",
        )

    monkeypatch.setattr(evaluator, "evaluate", fake_evaluate)
    scanner_result = SimpleNamespace(
        symbol="BTCUSDT",
        timeframe=SimpleNamespace(value="15m"),
        action=SimpleNamespace(value="LONG"),
        long_score=81,
        short_score=12,
        regime=SimpleNamespace(value="TRENDING_UP"),
        strategy="trend-following",
        scanned_at=datetime(2026, 8, 17, 7, 57, tzinfo=UTC),
    )

    await evaluator.evaluate_and_log(scanner_result)

    message, payload, level = state.storage.logs[0]
    assert message == "AI Haiku shadow evaluation"
    assert level == "INFO"
    assert payload is not None
    assert payload["symbol"] == "BTCUSDT"
    assert payload["timeframe"] == "15m"
    assert payload["baseline_action"] == "LONG"
    assert payload["baseline_long_score"] == 81
    assert payload["baseline_short_score"] == 12
    assert payload["baseline_regime"] == "TRENDING_UP"
    assert payload["baseline_strategy"] == "trend-following"
    assert isinstance(payload["correlation_id"], str)
    assert len(payload["correlation_id"]) == 20
    assert isinstance(payload["latency_ms"], float)
    assert payload["latency_ms"] >= 0
    assert payload["evaluated_at"].endswith("+00:00")
    assert payload["shadow_only"] is True
    assert payload["execution_enabled"] is False
    assert secret not in json.dumps(payload)


@pytest.mark.asyncio
async def test_shadow_correlation_id_is_stable_for_same_scanner_result(monkeypatch) -> None:
    from datetime import UTC, datetime

    from app.services.ai_shadow import AIShadowEvaluator, ShadowEvaluation

    state = SimpleNamespace(storage=FakeStorage())
    evaluator = AIShadowEvaluator(state)

    async def fake_evaluate(scanner_result: object) -> ShadowEvaluation:
        return ShadowEvaluation("FAIL_CLOSED", "anthropic", "haiku", error="timeout")

    monkeypatch.setattr(evaluator, "evaluate", fake_evaluate)
    scanner_result = SimpleNamespace(
        symbol="ETHUSDT",
        timeframe=SimpleNamespace(value="1h"),
        action=SimpleNamespace(value="SHORT"),
        long_score=10,
        short_score=88,
        regime=SimpleNamespace(value="TRENDING_DOWN"),
        strategy=None,
        scanned_at=datetime(2026, 8, 17, 7, 57, tzinfo=UTC),
    )

    await evaluator.evaluate_and_log(scanner_result)
    await evaluator.evaluate_and_log(scanner_result)

    first = state.storage.logs[0][1]
    second = state.storage.logs[1][1]
    assert first is not None and second is not None
    assert first["correlation_id"] == second["correlation_id"]
    assert state.storage.logs[0][2] == "WARNING"
    assert first["status"] == "FAIL_CLOSED"
    assert first["error"] == "timeout"


def test_haiku_module_has_no_execution_or_risk_dependencies() -> None:
    import ast
    import inspect

    from app.services import ai_shadow

    tree = ast.parse(inspect.getsource(ai_shadow))
    imports = {
        (node.module if isinstance(node, ast.ImportFrom) else alias.name) or ""
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    forbidden = ("execution", "exchange", "order_pipeline", "risk_engine", "portfolio_risk")
    assert not any(any(part in name for part in forbidden) for name in imports)


def test_auto_trader_never_reads_haiku_result() -> None:
    import inspect

    from app.services.auto_trader import AutoTrader

    source = inspect.getsource(AutoTrader._run_once_locked)
    assert "asyncio.create_task(evaluator.evaluate_and_log(result))" in source
    assert source.index("candidates =") < source.index("asyncio.create_task")
    assert "await evaluator" not in source
    assert "ai_shadow_evaluator" not in inspect.getsource(AutoTrader._effective_risk_engine)
