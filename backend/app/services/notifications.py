from app.domain.models import NotificationEvent, NotificationPayload


class NotificationService:
    def build(self, event: NotificationEvent, *, title: str, body: str, data: dict[str, str] | None = None) -> NotificationPayload:
        return NotificationPayload(event=event, title=title, body=body, data=data or {}, apns_ready=True)
