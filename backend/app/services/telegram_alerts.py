"""Telegram alert delivery (alerts trước, commands làm sau).

Gửi cảnh báo qua Telegram Bot API cho các sự kiện quan trọng. Có queue nền,
retry backoff, dedupe để không spam khi cùng một cảnh báo lặp lại.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

import httpx


class TelegramAlertService:
    BASE_URL = "https://api.telegram.org"
    DEDUPE_SECONDS = 60.0
    MAX_ATTEMPTS = 3
    MAX_QUEUE_SIZE = 200

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        *,
        context_provider: Callable[[], Mapping[str, Any]] | None = None,
    ) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.context_provider = context_provider
        self.queue: asyncio.Queue[tuple[str, str, dict[str, Any]]] = asyncio.Queue(
            maxsize=self.MAX_QUEUE_SIZE
        )
        self.task: asyncio.Task[None] | None = None
        self.command_task: asyncio.Task[None] | None = None
        self.running = False
        self.command_handler: Callable[[str, str], Awaitable[str]] | None = None
        self.update_offset: int | None = None
        self._recent: dict[str, float] = {}
        self.sent_count = 0
        self.dropped_count = 0
        self.command_count = 0
        self.command_replies = 0
        self.unauthorized_count = 0
        self.last_command: str | None = None
        self.last_command_at: datetime | None = None

    @property
    def configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def start(self, command_handler: Callable[[str, str], Awaitable[str]] | None = None) -> None:
        if not self.configured or (self.task and not self.task.done()):
            return
        self.command_handler = command_handler
        self.running = True
        self.task = asyncio.create_task(self._worker())
        if command_handler is not None:
            self.command_task = asyncio.create_task(self._command_worker())

    async def stop(self) -> None:
        self.running = False
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        if self.command_task and not self.command_task.done():
            self.command_task.cancel()
            try:
                await self.command_task
            except asyncio.CancelledError:
                pass

    async def send_alert(
        self, event: str, title: str, body: str, *, data: dict[str, Any] | None = None
    ) -> bool:
        """Xếp hàng một cảnh báo; trả về False nếu bị dedupe hoặc chưa cấu hình."""
        if not self.configured:
            return False
        key = f"{event}|{title}|{body}"
        now = time.monotonic()
        last = self._recent.get(key)
        if last is not None and now - last < self.DEDUPE_SECONDS:
            self.dropped_count += 1
            return False
        self._recent[key] = now
        try:
            context: dict[str, Any] = {}
            if self.context_provider is not None:
                try:
                    context = dict(self.context_provider())
                except Exception:  # noqa: BLE001 - context không được làm mất alert
                    context = {}
            self.queue.put_nowait((event, title, {**(data or {}), **context, "body": body}))
        except asyncio.QueueFull:
            self._recent.pop(key, None)
            self.dropped_count += 1
            return False
        return True

    def format_message(self, event: str, title: str, data: dict[str, Any]) -> str:
        """Render concise Vietnamese operator alerts without leaking raw internals."""
        event_key = event.upper()
        templates = {
            "POSITION_OPEN": ("✅", "INFO", "ĐÃ MỞ VỊ THẾ", "Theo dõi SL/TP bảo vệ."),
            "POSITION_CLOSE": ("✅", "INFO", "ĐÃ ĐÓNG VỊ THẾ", "Kiểm tra PnL và phí thực nhận."),
            "TP": ("🎯", "INFO", "CẬP NHẬT CHỐT LỜI", "Không cần thao tác nếu lệnh bảo vệ vẫn đủ."),
            "SL": ("⚠️", "WARNING", "DỪNG LỖ", "Kiểm tra vị thế đã đóng và không còn lệnh mồ côi."),
            "RISK_LIMIT": ("⚠️", "WARNING", "GIỚI HẠN RỦI RO", "Entry mới đã bị chặn; không tăng khối lượng."),
            "API_DISCONNECT": ("🚨", "CRITICAL", "MẤT KẾT NỐI SÀN", "Giữ bot dừng và kiểm tra reconciliation."),
            "SAFE_MODE": ("🚨", "CRITICAL", "SAFE MODE", "Không resume trước khi xử lý nguyên nhân."),
            "EMERGENCY_STOP": ("🚨", "CRITICAL", "DỪNG KHẨN CẤP", "Entry mới bị khóa; kiểm tra vị thế bảo vệ."),
        }
        icon, severity, heading, action = templates.get(
            event_key,
            ("ℹ️", "INFO", title.upper() or event_key, "Kiểm tra dashboard nếu cần thêm chi tiết."),
        )
        labels = {
            "mode": "Chế độ",
            "exchange": "Sàn",
            "bot_state": "Bot",
            "live_enabled": "LIVE",
            "safe_mode": "SAFE_MODE",
            "emergency_stop": "Dừng khẩn cấp",
            "symbol": "Mã",
            "side": "Hướng",
            "quantity": "Khối lượng",
            "entry_price": "Giá vào",
            "exit_price": "Giá đóng",
            "last_fill_price": "Giá khớp gần nhất",
            "stop_loss": "Dừng lỗ",
            "take_profit": "Chốt lời",
            "take_profits": "Các mức chốt lời",
            "old_stop": "SL cũ",
            "new_stop": "SL mới",
            "realized_pnl": "PnL thực nhận",
            "client_order_id": "Mã lệnh",
            "reason": "Lý do",
        }
        context_keys = (
            "mode",
            "exchange",
            "bot_state",
            "live_enabled",
            "safe_mode",
            "emergency_stop",
        )
        body = str(data.get("body") or "").strip()
        lines = [f"{icon} {heading} · {severity}"]
        # Safety boundary first, from the queued snapshot (not live-mutated state).
        if data.get("mode") is not None or data.get("live_enabled") is not None:
            mode = self._format_context_value("mode", data.get("mode", "UNKNOWN"))
            live = self._format_context_value("live_enabled", data.get("live_enabled", False))
            lines.append(f"🔒 Phạm vi: {mode} · LIVE {live}")
        if title and title.upper() not in {heading, event_key}:
            lines.append(f"📌 {self._humanize_title(title, event_key)}")
        detail_order = (
            "symbol",
            "side",
            "quantity",
            "entry_price",
            "exit_price",
            "last_fill_price",
            "stop_loss",
            "take_profit",
            "take_profits",
            "old_stop",
            "new_stop",
            "realized_pnl",
            "reason",
            "client_order_id",
        )
        shown: set[str] = {"body", *context_keys}
        for key in context_keys:
            value = data.get(key)
            if value in (None, ""):
                continue
            lines.append(f"• {labels[key]}: {self._format_context_value(key, value)}")
        if body:
            lines.append(f"📝 {body}")
        for key in detail_order:
            value = data.get(key)
            if value in (None, ""):
                continue
            lines.append(
                f"• {labels.get(key, key.replace('_', ' ').title())}: "
                f"{self._format_detail_value(key, value)}"
            )
            shown.add(key)
        for key, value in data.items():
            if key in shown or value in (None, ""):
                continue
            lines.append(
                f"• {labels.get(key, key.replace('_', ' ').title())}: "
                f"{self._format_detail_value(key, value)}"
            )
        lines.append(f"➡️ {action}")
        lines.append(f"🕒 {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        return "\n".join(lines)[:4000]

    @staticmethod
    def _humanize_title(title: str, event_key: str) -> str:
        """Map leftover English operator titles to short Vietnamese labels."""
        cleaned = " ".join(str(title or "").split())
        if not cleaned:
            return event_key
        aliases = {
            "POSITION OPEN": "Mở vị thế",
            "POSITION CLOSE": "Đóng vị thế",
            "TP PROTECTION": "Bảo vệ chốt lời",
            "SAFE_MODE": "SAFE MODE",
            "SAFE MODE": "SAFE MODE",
            "EMERGENCY STOP": "Dừng khẩn cấp",
            "API DISCONNECT": "Mất kết nối sàn",
            "RISK LIMIT": "Giới hạn rủi ro",
        }
        key = cleaned.upper().replace("-", " ")
        if key in aliases:
            return aliases[key]
        if cleaned.upper() in {event_key, event_key.replace("_", " ")}:
            return cleaned
        # Keep unknown titles, but strip noisy ALL-CAPS English where possible.
        return cleaned

    @staticmethod
    def _format_detail_value(key: str, value: Any) -> str:
        if key == "side":
            side = str(value).upper()
            hints = {"LONG": "mua", "SHORT": "bán", "BUY": "mua", "SELL": "bán"}
            return f"{side} · {hints[side]}" if side in hints else side
        if key in {
            "quantity",
            "entry_price",
            "exit_price",
            "last_fill_price",
            "stop_loss",
            "take_profit",
            "old_stop",
            "new_stop",
            "realized_pnl",
        }:
            try:
                number = float(value)
            except (TypeError, ValueError):
                return str(value)
            if key == "quantity":
                return f"{number:g}"
            if abs(number) >= 1000:
                return f"{number:,.2f}".rstrip("0").rstrip(".")
            return f"{number:.6f}".rstrip("0").rstrip(".")
        if key == "take_profits" and isinstance(value, (list, tuple)):
            parts: list[str] = []
            for item in value:
                try:
                    parts.append(f"{float(item):g}")
                except (TypeError, ValueError):
                    parts.append(str(item))
            return ", ".join(parts) if parts else "—"
        return str(value)

    @staticmethod
    def _format_context_value(key: str, value: Any) -> str:
        if isinstance(value, bool):
            if key == "live_enabled":
                return "BẬT · có thể gửi lệnh" if value else "TẮT · không gửi lệnh"
            return "BẬT" if value else "TẮT"
        if key == "mode":
            hints = {
                "DEMO": "không dùng vốn thật",
                "PAPER": "mô phỏng nội bộ",
                "LIVE": "vốn thật",
            }
            state = str(value)
            return f"{state} · {hints.get(state, 'cần kiểm tra')}"
        if key == "bot_state":
            hints = {
                "STOPPED": "không phát lệnh",
                "RUNNING": "đang chạy",
                "PAUSED": "tạm dừng entry",
                "SAFE_MODE": "khóa entry",
            }
            state = str(value)
            return f"{state} · {hints.get(state, 'cần kiểm tra')}"
        if key == "exchange":
            hints = {
                "CONNECTED": "đã kết nối",
                "DISCONNECTED": "chưa kết nối",
                "STALE": "dữ liệu cũ",
                "SAFE_MODE": "đang khóa",
            }
            state = str(value)
            return f"{state} · {hints.get(state, 'cần kiểm tra')}"
        return str(value)

    async def _worker(self) -> None:
        while self.running:
            try:
                event, title, data = await asyncio.wait_for(self.queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            try:
                await self._deliver(event, title, data)
            except Exception:  # noqa: BLE001 - một alert lỗi không được giết worker
                self.dropped_count += 1
            finally:
                self.queue.task_done()

    async def _deliver(self, event: str, title: str, data: dict[str, Any]) -> None:
        message = self.format_message(event, title, data)
        for attempt in range(self.MAX_ATTEMPTS):
            try:
                ok = await self._post_message(message)
                if ok:
                    self.sent_count += 1
                    return
            except (httpx.HTTPError, OSError):
                pass
            await asyncio.sleep(0.5 * (2**attempt))
        self.dropped_count += 1

    async def _post_message(self, message: str) -> bool:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{self.BASE_URL}/bot{self.bot_token}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "disable_web_page_preview": True,
                },
            )
        if response.status_code == 429:
            retry_after = float(response.json().get("parameters", {}).get("retry_after", 3))
            await asyncio.sleep(retry_after)
            return False
        return response.status_code < 400

    async def _command_worker(self) -> None:
        while self.running:
            try:
                updates = await self._poll_updates()
            except (httpx.HTTPError, OSError, ValueError):
                await asyncio.sleep(3.0)
                continue
            for update in updates:
                try:
                    await asyncio.wait_for(self._handle_update(update), timeout=15.0)
                except Exception:  # noqa: BLE001 - command lỗi không được làm chết polling worker
                    self.dropped_count += 1
            await asyncio.sleep(1.0)

    async def _poll_updates(self) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": 20,
            "allowed_updates": ["message"],
        }
        if self.update_offset is not None:
            payload["offset"] = self.update_offset
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.BASE_URL}/bot{self.bot_token}/getUpdates",
                json=payload,
            )
        if response.status_code == 409:
            # Another bot process is polling. Alerts can still be sent safely.
            await asyncio.sleep(10.0)
            return []
        if response.status_code >= 400:
            response.raise_for_status()
        body = response.json()
        rows = body.get("result", [])
        return rows if isinstance(rows, list) else []

    async def _handle_update(self, update: dict[str, Any]) -> None:
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            self.update_offset = update_id + 1
        message = update.get("message")
        if not isinstance(message, dict):
            return
        chat = message.get("chat")
        text = str(message.get("text") or "").strip()
        incoming_chat_id = str((chat or {}).get("id") if isinstance(chat, dict) else "")
        if incoming_chat_id != str(self.chat_id):
            self.unauthorized_count += 1
            return
        if not text.startswith("/"):
            return
        command, _, args = text.partition(" ")
        command = command.split("@", 1)[0].lower()
        self.command_count += 1
        self.last_command = command
        self.last_command_at = datetime.now(UTC)
        if self.command_handler is None:
            reply = "Telegram command handler chưa sẵn sàng."
        else:
            reply = await self.command_handler(command, args.strip())
        if await self._post_message(reply[:4000]):
            self.command_replies += 1

    def status(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "commands_enabled": self.configured and self.command_handler is not None,
            "worker_alive": self.task is not None and not self.task.done(),
            "command_worker_alive": self.command_task is not None and not self.command_task.done(),
            "queued": self.queue.qsize(),
            "queue_capacity": self.MAX_QUEUE_SIZE,
            "sent": self.sent_count,
            "dropped": self.dropped_count,
            "commands": self.command_count,
            "command_replies": self.command_replies,
            "unauthorized": self.unauthorized_count,
            "last_command": self.last_command,
            "last_command_at": self.last_command_at.isoformat() if self.last_command_at else None,
        }
