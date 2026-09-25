"""Delivery channels (FR-ALT-004): web (in-app), email, Microsoft Teams, Slack, signed outbound webhook."""

from __future__ import annotations

import json
import smtplib
import ssl
import time
from email.message import EmailMessage
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.crypto import hmac_sign


class DeliveryError(Exception):
    pass


def _post(url: str, body: dict[str, Any], headers: dict[str, str] | None = None) -> None:
    if not url.startswith("https://") and get_settings().env == "production":
        raise DeliveryError("only https destinations are allowed in production")
    try:
        r = httpx.post(url, content=json.dumps(body).encode(), headers={"Content-Type": "application/json", **(headers or {})},
                       timeout=15.0)
    except httpx.HTTPError as e:
        raise DeliveryError(f"transport error: {e}") from e
    if r.status_code >= 300:
        raise DeliveryError(f"HTTP {r.status_code}: {r.text[:200]}")


def render_text(payload: dict[str, Any]) -> str:
    lines = [payload["title"], ""]
    for item in payload.get("items", [payload]):
        if item is not payload:
            lines.append(f"## {item['title']}")
        for label, key in (("Affected internal asset", "affected_assets"), ("Verified change", "verified_change"),
                           ("Why flagged", "why_flagged"), ("What is known", "known"), ("What is unknown", "unknown"),
                           ("Interpretation (AI, unverified)", "interpretation"),
                           ("Recommended investigation", "recommended_investigation"), ("Evidence", "evidence"),
                           ("Materiality", "materiality"), ("Review status", "review_status"),
                           ("Updated since last notification", "update_summary")):
            v = item.get(key)
            if v:
                lines.append(f"{label}: {'; '.join(v) if isinstance(v, list) else v}")
        if item.get("link"):
            lines.append(f"Full event detail: {item['link']}")
        lines.append("")
    lines.append("Decision-support output. Facts are evidence-linked; interpretations are AI-generated hypotheses.")
    return "\n".join(lines)


def send_email(recipients: list[str], payload: dict[str, Any]) -> None:
    s = get_settings()
    if not s.smtp_host:
        raise DeliveryError("SMTP not configured")
    msg = EmailMessage()
    msg["Subject"] = payload["title"][:200]
    msg["From"] = s.smtp_from
    msg["To"] = ", ".join(recipients)
    msg.set_content(render_text(payload))
    ctx = ssl.create_default_context()
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
        smtp.starttls(context=ctx)
        if s.smtp_username and s.smtp_password:
            smtp.login(s.smtp_username, s.smtp_password.get_secret_value())
        smtp.send_message(msg)


def send_slack(url: str, payload: dict[str, Any]) -> None:
    text = render_text(payload)
    _post(url, {"text": payload["title"], "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text[:2900]}}]})


def send_teams(url: str, payload: dict[str, Any]) -> None:
    _post(url, {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": [{"type": "TextBlock", "text": payload["title"], "weight": "Bolder", "wrap": True},
                                 {"type": "TextBlock", "text": render_text(payload)[:20000], "wrap": True}]},
        }],
    })


def send_webhook(url: str, payload: dict[str, Any]) -> None:
    ts = str(int(time.time()))
    body = json.dumps(payload, sort_keys=True, default=str).encode()
    sig = hmac_sign(ts.encode() + b"." + body, get_settings().webhook_signing_secret.get_secret_value())
    _post(url, json.loads(body), {"X-XData-Timestamp": ts, "X-XData-Signature": f"sha256={sig}"})


def deliver(channel: str, destinations: dict[str, Any], payload: dict[str, Any]) -> None:
    if channel == "web":
        return  # persisted Notification row is the in-app inbox item
    if channel == "email":
        to = destinations.get("email") or []
        if not to:
            raise DeliveryError("no email recipients")
        send_email(to, payload)
    elif channel == "slack":
        send_slack(destinations["slack_webhook"], payload)
    elif channel == "teams":
        send_teams(destinations["teams_webhook"], payload)
    elif channel == "webhook":
        send_webhook(destinations["webhook_url"], payload)
    else:
        raise DeliveryError(f"unknown channel {channel}")
