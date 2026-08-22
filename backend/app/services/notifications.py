from typing import Any

from app.domain.models import NotificationEvent, NotificationPayload
from app.services.telegram_alerts import TelegramAlertService


class NotificationService:
    def __init__(self, telegram: TelegramAlertService | None = None) -> None:
        self.telegram = telegram

    def build(
        self,
        event: NotificationEvent,
        *,
        title: str,
        body: str,
        data: dict[str, str] | None = None,
    ) -> NotificationPayload:
        return NotificationPayload(
            event=event, title=title, body=body, data=data or {}, apns_ready=True
        )

    async def alert(
        self,
        event: NotificationEvent,
        *,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
    ) -> NotificationPayload:
        """Build payload và đẩy cảnh báo Telegram (không chặn luồng gọi)."""
        payload = self.build(event, title=title, body=body, data=_stringify(data))
        if self.telegram is not None:
            await self.telegram.send_alert(event.value, title, body, data=data)
        return payload


def _stringify(data: dict[str, Any] | None) -> dict[str, str]:
    return {str(key): str(value) for key, value in (data or {}).items()}
