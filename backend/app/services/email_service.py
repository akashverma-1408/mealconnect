"""E-mail sending behind a tiny interface.

Development uses the console backend (the e-mail is written to the worker log).
In production this would be Amazon SES / SendGrid — only `send_email` changes.
"""

import logging

from app.core.config import settings

logger = logging.getLogger("app.email")


def send_email(to: str, subject: str, body: str) -> None:
    if settings.EMAIL_BACKEND == "console":
        logger.info("email sent", extra={"to": to, "subject": subject, "body": body})
        return
    raise RuntimeError(f"Unknown EMAIL_BACKEND {settings.EMAIL_BACKEND}")
