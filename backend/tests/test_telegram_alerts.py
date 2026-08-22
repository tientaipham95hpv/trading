from app.services.telegram_alerts import TelegramAlertService


def test_alert_format_is_operator_friendly_and_vietnamese() -> None:
    service = TelegramAlertService("token", "123")

    message = service.format_message(
        "SAFE_MODE",
        "SAFE_MODE",
        {
            "body": "Thiếu stop bảo vệ",
            "mode": "DEMO",
            "live_enabled": False,
            "bot_state": "STOPPED",
            "symbol": "BTCUSDT",
            "side": "LONG",
        },
    )

    assert message.startswith("🚨 SAFE MODE · CRITICAL")
    assert "🔒 Phạm vi: DEMO · không dùng vốn thật · LIVE TẮT · không gửi lệnh" in message
    assert "Thiếu stop bảo vệ" in message
    assert "• Chế độ: DEMO · không dùng vốn thật" in message
    assert "• LIVE: TẮT · không gửi lệnh" in message
    assert "• Bot: STOPPED · không phát lệnh" in message
    assert "• Mã: BTCUSDT" in message
    assert "• Hướng: LONG · mua" in message
    assert "➡️ Không resume trước khi xử lý nguyên nhân." in message
    assert message.endswith("UTC")
    assert "[SAFE_MODE]" not in message


def test_english_titles_are_humanized_for_operators() -> None:
    service = TelegramAlertService("token", "123")

    message = service.format_message(
        "POSITION_OPEN",
        "Position open",
        {
            "body": "BTCUSDT LONG",
            "mode": "DEMO",
            "live_enabled": False,
            "symbol": "BTCUSDT",
            "side": "LONG",
            "quantity": 0.01,
            "entry_price": 65000.5,
        },
    )

    assert message.startswith("✅ ĐÃ MỞ VỊ THẾ · INFO")
    assert "📌 Mở vị thế" in message
    assert "Position open" not in message
    assert "• Khối lượng: 0.01" in message
    assert "• Giá vào: 65,000.5" in message


def test_lifecycle_alert_shows_warning_severity_and_exit_price() -> None:
    service = TelegramAlertService("token", "123")

    message = service.format_message(
        "SL",
        "Dừng lỗ · BTCUSDT",
        {"symbol": "BTCUSDT", "exit_price": 64000.0, "realized_pnl": -12.5},
    )

    assert message.startswith("⚠️ DỪNG LỖ · WARNING")
    assert "• Giá đóng: 64,000" in message
    assert "• PnL thực nhận: -12.5" in message


async def test_telegram_commands_are_allowlisted_and_replied() -> None:
    replies: list[str] = []
    service = TelegramAlertService("token", "123")

    async def handler(command: str, args: str) -> str:
        return f"{command}:{args}"

    async def fake_post(message: str) -> bool:
        replies.append(message)
        return True

    service.command_handler = handler
    service._post_message = fake_post  # type: ignore[method-assign]

    await service._handle_update(
        {
            "update_id": 41,
            "message": {"chat": {"id": 123}, "text": "/status now"},
        }
    )
    await service._handle_update(
        {
            "update_id": 42,
            "message": {"chat": {"id": 999}, "text": "/pause"},
        }
    )

    assert replies == ["/status:now"]
    assert service.update_offset == 43
    assert service.status()["commands"] == 1
    assert service.status()["command_replies"] == 1
    assert service.status()["unauthorized"] == 1


async def test_full_queue_drops_without_blocking() -> None:
    import asyncio

    service = TelegramAlertService("token", "123")
    service.queue = asyncio.Queue(maxsize=1)
    service.queue.put_nowait(("SL", "first", {}))

    assert await service.send_alert("SL", "second", "body") is False
    assert service.dropped_count == 1


async def test_command_worker_continues_after_unexpected_handler_error() -> None:
    import asyncio

    service = TelegramAlertService("token", "123")
    handled: list[int] = []

    async def fake_poll() -> list[dict[str, object]]:
        if handled:
            service.running = False
            return []
        return [
            {"update_id": 1, "message": {"chat": {"id": 123}, "text": "/bad"}},
            {"update_id": 2, "message": {"chat": {"id": 123}, "text": "/good"}},
        ]

    async def fake_handle(update: dict[str, object]) -> None:
        update_id = int(update["update_id"])  # type: ignore[arg-type]
        handled.append(update_id)
        if update_id == 1:
            raise RuntimeError("unexpected command failure")
        service.running = False

    service._poll_updates = fake_poll  # type: ignore[method-assign]
    service._handle_update = fake_handle  # type: ignore[method-assign]
    service.running = True

    await asyncio.wait_for(service._command_worker(), timeout=2)

    assert handled == [1, 2]
    assert service.dropped_count == 1


async def test_alert_worker_continues_after_bad_item() -> None:
    import asyncio

    service = TelegramAlertService("token", "123")
    delivered: list[str] = []

    async def fake_deliver(event: str, title: str, data: dict[str, object]) -> None:
        if title == "bad":
            raise ValueError("malformed")
        delivered.append(title)
        service.running = False

    service._deliver = fake_deliver  # type: ignore[method-assign]
    service.running = True
    service.queue.put_nowait(("SL", "bad", {}))
    service.queue.put_nowait(("TP", "good", {}))
    await asyncio.wait_for(service._worker(), timeout=1)

    assert delivered == ["good"]
    assert service.dropped_count == 1
