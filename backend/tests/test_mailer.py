import smtplib
import stat
import os

import pytest

from app.services import mailer


@pytest.fixture
def mail_config(monkeypatch, tmp_path):
    values = {
        "HOST": "smtp.gmail.com", "PORT": "587", "SECURITY": "starttls",
        "USERNAME": "sender@example.test", "PASSWORD": "",
        "DEFAULT_FROM": "sender@example.test", "ALLOWED_FROM": "sender@example.test",
        "DEFAULT_TO": "receiver@example.test",
    }
    for key, value in values.items():
        monkeypatch.setenv("BIOFLOW_SMTP_" + key, value)
    path = tmp_path / "private" / "mail.env"
    monkeypatch.setattr(mailer, "RUNTIME_MAIL_FILE", path)
    return path


def test_defaults_available_before_smtp_authentication(client, mail_config):
    response = client.get("/api/v1/mail/settings")
    assert response.status_code == 200
    data = response.json()
    assert data["configured"] is False
    assert data["default_sender"] == "sender@example.test"
    assert data["default_recipient"] == "receiver@example.test"
    assert data["allowed_senders"] == ["sender@example.test"]
    assert data["connection_setup_available"] is True
    assert "password" not in data


def test_smtp_configuration_requires_approver(client, mail_config):
    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/mail/settings").status_code == 401
    assert client.post("/api/v1/mail/connect", json={"app_password": "abcdefghijklmnop"}).status_code == 401
    assert not mail_config.exists()


def test_invalid_credential_is_not_reflected_or_stored(client, mail_config):
    secret = "not-an-app-password"
    response = client.post("/api/v1/mail/connect", json={"app_password": secret})
    assert response.status_code == 422
    assert secret not in response.text
    assert not mail_config.exists()


def test_connect_verifies_tls_auth_without_sending_and_saves_privately(client, mail_config, monkeypatch):
    events = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ("smtp.gmail.com", 587, 25)
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def ehlo(self): events.append("ehlo")
        def starttls(self, context): events.append("tls")
        def login(self, username, password):
            assert username == "sender@example.test"
            assert password == "abcdefghijklmnop"
            events.append("auth")
        def send_message(self, *args, **kwargs):
            pytest.fail("Connecting SMTP must not send email")

    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    response = client.post("/api/v1/mail/connect", json={"app_password": "abcd efgh ijkl mnop"})
    assert response.status_code == 200
    assert response.json()["configured"] is True
    assert response.json()["status"] == "connected"
    assert "abcdefghijklmnop" not in response.text
    assert events == ["ehlo", "tls", "ehlo", "auth"]
    if os.name != 'nt':  # Windows chmod does not expose POSIX owner/group bits.
        assert stat.S_IMODE(mail_config.stat().st_mode) == 0o600
    assert mailer.mail_configuration().password == "abcdefghijklmnop"
    monkeypatch.setenv("BIOFLOW_SMTP_USERNAME", "other@example.test")
    assert mailer.mail_configuration().password == ""


def test_authentication_failure_does_not_save_credentials(client, mail_config, monkeypatch):
    class RejectedSMTP:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def ehlo(self): pass
        def starttls(self, context): pass
        def login(self, *args):
            raise smtplib.SMTPAuthenticationError(535, b"provider diagnostic")

    monkeypatch.setattr(mailer.smtplib, "SMTP", RejectedSMTP)
    response = client.post("/api/v1/mail/connect", json={"app_password": "abcdefghijklmnop"})
    assert response.status_code == 502
    assert "abcdefghijklmnop" not in response.text
    assert "provider diagnostic" not in response.text
    assert not mail_config.exists()
    assert mailer.public_mail_settings()["configured"] is False
