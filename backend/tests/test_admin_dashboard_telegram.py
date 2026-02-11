from app.api.v1 import admin_dashboard as mod


class _Resp:
    def __init__(self, ok: bool):
        self.ok = ok


def test_send_admin_telegram_message_uses_telegram_bot_token(monkeypatch):
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "12345:valid_token_test")
    monkeypatch.setenv("ADMIN_CHAT_ID", "777")

    called = {}

    def fake_post(url, data, timeout):
        called["url"] = url
        called["data"] = data
        called["timeout"] = timeout
        return _Resp(True)

    monkeypatch.setattr(mod.requests, "post", fake_post)

    assert mod._send_admin_telegram_message("hello") is True
    assert called["url"] == "https://api.telegram.org/bot12345:valid_token_test/sendMessage"
    assert called["data"] == {"chat_id": "777", "text": "hello"}
    assert called["timeout"] == 8


def test_send_admin_telegram_message_ignores_placeholder_token(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "${BOT_TOKEN}")
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.setenv("ADMIN_CHAT_ID", "777")

    assert mod._send_admin_telegram_message("hello") is False
