"""
Optional SMTP connectivity check. Loads settings from `.env` next to `manage.py`
(same file Django uses). Do not put secrets in this file.
"""
import os
import smtplib
import sys
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH)


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"Missing or empty environment variable: {name}", file=sys.stderr)
        print(f"Define it in {_ENV_PATH} (see example.env).", file=sys.stderr)
        sys.exit(1)
    return value


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def test_smtp():
    host = _require("EMAIL_HOST")
    port = int(os.environ.get("EMAIL_PORT", "587") or "587")
    user = _require("EMAIL_HOST_USER")
    password = _require("EMAIL_HOST_PASSWORD")
    sender = os.environ.get("DEFAULT_FROM_EMAIL", "").strip() or user
    receiver = _require("SMTP_TEST_TO_EMAIL")
    use_tls = _env_bool("EMAIL_USE_TLS", default=True)
    use_ssl = _env_bool("EMAIL_USE_SSL", default=False)

    print(f"Connecting to {host}:{port}...")
    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=10)
        else:
            server = smtplib.SMTP(host, port, timeout=10)
            if use_tls:
                server.starttls()
        print("Logging in...")
        server.login(user, password)

        msg = MIMEText("Network Test: SMTP connectivity OK.")
        msg["Subject"] = "Network Test"
        msg["From"] = sender
        msg["To"] = receiver

        print("Sending mail...")
        server.sendmail(sender, [receiver], msg.as_string())
        server.quit()
        print("Success! Network allows SMTP traffic.")
    except Exception as e:
        print(f"Failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    test_smtp()
