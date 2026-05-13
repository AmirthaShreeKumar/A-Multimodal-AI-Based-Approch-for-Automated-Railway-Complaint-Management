"""
Multi-channel SOS: Twilio SMS, Twilio WhatsApp, SMTP email, ntfy push.

At least one channel must succeed. Configure any subset in .env.
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formatdate
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _clip(s: str, max_len: int) -> str:
    s = (s or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def _clip_gsm7(s: str, max_len: int) -> str:
    """ASCII ellipsis so the whole SMS can stay GSM-7 (one segment @ 160 chars)."""
    s = (s or "").strip()
    if len(s) <= max_len:
        return s
    if max_len <= 3:
        return s[:max_len]
    return s[: max_len - 3] + "..."


def normalize_e164(raw: str) -> str:
    r = "".join(c for c in (raw or "").strip() if c.isdigit() or c == "+")
    if not r:
        return ""
    if r.startswith("+"):
        return r
    digits = r.replace("+", "")
    if len(digits) == 10:
        return "+91" + digits
    if len(digits) == 11 and digits.startswith("0"):
        return "+91" + digits[1:]
    if len(digits) == 12 and digits.startswith("91"):
        return "+" + digits
    return "+" + digits


def sos_phone_destinations() -> List[str]:
    raw = os.environ.get("SOS_SMS_TO", "").strip()
    if raw:
        parts = [normalize_e164(x.strip()) for x in raw.replace(";", ",").split(",")]
        return [p for p in parts if len(p) >= 11]
    return ["+919443081888"]


def build_sos_body(
    logged_in_username: str,
    manifest,
    latitude: float,
    longitude: float,
    accuracy_m: Optional[float],
) -> str:
    ph = (getattr(manifest, "phone", None) or "").strip() or "—"
    email = _clip((manifest.email or "").strip(), 42)
    train = _clip(manifest.train_name, 48)
    route = _clip(manifest.location, 56)
    acc = f"{accuracy_m:.0f}m" if accuracy_m is not None else "?"
    maps = f"https://www.google.com/maps?q={latitude:.6f},{longitude:.6f}"
    return (
        f"RailMadad SOS\n"
        f"User:{logged_in_username} PNR:{manifest.pnr}\n"
        f"Ph:{ph}\n"
        f"Mail:{email}\n"
        f"Train:{train} Seat:{manifest.seat}\n"
        f"Route:{route}\n"
        f"GPS:{latitude:.6f},{longitude:.6f} ~{acc}\n"
        f"{maps}"
    )


def build_sos_sms_body(
    logged_in_username: str,
    manifest,
    latitude: float,
    longitude: float,
) -> str:
    """
    One short SMS line so Twilio Trial stays within a single segment (error 30044).
    Full details go via WhatsApp, email, and ntfy.
    """
    max_chars = int(os.environ.get("SOS_SMS_MAX_CHARS", "160") or "160")
    max_chars = max(72, min(max_chars, 1500))

    user = _clip_gsm7(logged_in_username, 22)
    pnr = _clip_gsm7(str(getattr(manifest, "pnr", "") or "").replace(" ", ""), 14)
    lat_s = f"{latitude:.5f}"
    lon_s = f"{longitude:.5f}"
    maps = f"https://maps.google.com/?q={lat_s},{lon_s}"
    line = f"RailMadad SOS {user} PNR:{pnr} {maps}".strip()
    if len(line) > max_chars:
        line = f"SOS PNR:{pnr} {maps}".strip()
    if len(line) > max_chars:
        line = f"SOS {maps}".strip()
    if len(line) > max_chars:
        line = line[: max_chars - 3] + "..." if max_chars > 3 else line[:max_chars]
    return line


def _twilio_credentials() -> Optional[Tuple[str, str]]:
    sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
    token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
    if not sid or not token:
        return None
    return sid, token


def twilio_sms_from() -> Optional[str]:
    n = normalize_e164(os.environ.get("TWILIO_PHONE_NUMBER", "").strip())
    if not n or len(n) < 11:
        return None
    return n


def twilio_whatsapp_from() -> Optional[str]:
    """
    E.g. whatsapp:+14155238886 (Twilio sandbox) or whatsapp:+1… your approved sender.
    """
    raw = os.environ.get("TWILIO_WHATSAPP_FROM", "").strip()
    if not raw:
        return None
    if raw.lower().startswith("whatsapp:"):
        return raw
    return "whatsapp:" + raw


def _channel_sms(body: str, destinations: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": False, "detail": "skipped", "messages": []}
    cred = _twilio_credentials()
    from_num = twilio_sms_from()
    if not cred or not from_num:
        out["detail"] = "not configured (TWILIO_* + TWILIO_PHONE_NUMBER)"
        return out
    try:
        from twilio.rest import Client
    except ImportError:
        out["detail"] = "pip install twilio"
        return out

    client = Client(cred[0], cred[1])
    sent = 0
    last_err = ""
    for to in destinations:
        try:
            msg = client.messages.create(body=body, from_=from_num, to=to)
            sent += 1
            out["messages"].append(
                {"to": to, "sid": getattr(msg, "sid", ""), "status": getattr(msg, "status", "")}
            )
            logger.info("SOS SMS sid=%s to=%s", getattr(msg, "sid", ""), to)
        except Exception as e:
            last_err = str(e)
            logger.warning("SOS SMS fail to=%s: %s", to, e)
    out["ok"] = sent > 0
    out["detail"] = "" if out["ok"] else (last_err or "failed")
    return out


def _channel_whatsapp(body: str, destinations: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": False, "detail": "skipped", "messages": []}
    cred = _twilio_credentials()
    from_wa = twilio_whatsapp_from()
    if not cred or not from_wa:
        out["detail"] = "not configured (TWILIO_WHATSAPP_FROM)"
        return out
    if len(body) > 4000:
        body = body[:3997] + "…"
    try:
        from twilio.rest import Client
    except ImportError:
        out["detail"] = "pip install twilio"
        return out

    client = Client(cred[0], cred[1])
    sent = 0
    last_err = ""
    for to in destinations:
        to_wa = to if str(to).startswith("whatsapp:") else f"whatsapp:{to}"
        try:
            msg = client.messages.create(body=body, from_=from_wa, to=to_wa)
            sent += 1
            out["messages"].append(
                {"to": to_wa, "sid": getattr(msg, "sid", ""), "status": getattr(msg, "status", "")}
            )
            logger.info("SOS WhatsApp sid=%s to=%s", getattr(msg, "sid", ""), to_wa)
        except Exception as e:
            last_err = str(e)
            logger.warning("SOS WhatsApp fail to=%s: %s", to_wa, e)
    out["ok"] = sent > 0
    out["detail"] = "" if out["ok"] else (last_err or "failed")
    return out


def smtp_config() -> Optional[dict]:
    server = os.environ.get("MAIL_SERVER", "").strip()
    if not server:
        return None
    port = int(os.environ.get("MAIL_PORT", "587") or "587")
    user = os.environ.get("MAIL_USERNAME", "").strip()
    password = os.environ.get("MAIL_PASSWORD", "").strip()
    sender = (os.environ.get("MAIL_DEFAULT_SENDER") or user or "").strip()
    if not sender:
        return None
    use_tls = os.environ.get("MAIL_USE_TLS", "true").lower() in ("1", "true", "yes")
    return {
        "server": server,
        "port": port,
        "user": user,
        "password": password,
        "sender": sender,
        "use_tls": use_tls,
    }


def sos_email_destinations() -> List[str]:
    raw = os.environ.get("SOS_EMAIL_TO", "").strip()
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def _channel_email(
    subject: str, body: str, logged_in_username: str, manifest
) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": False, "detail": "skipped"}
    recipients = sos_email_destinations()
    cfg = smtp_config()
    if not recipients:
        out["detail"] = "no SOS_EMAIL_TO"
        return out
    if not cfg:
        out["detail"] = "MAIL_SERVER / MAIL_DEFAULT_SENDER not set"
        return out

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["sender"]
    msg["To"] = ", ".join(recipients)
    msg["Reply-To"] = manifest.email
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(body + f"\n\n— RailMadad · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

    try:
        if cfg["use_tls"]:
            context = ssl.create_default_context()
            with smtplib.SMTP(cfg["server"], cfg["port"], timeout=30) as smtp:
                smtp.starttls(context=context)
                if cfg["user"] and cfg["password"]:
                    smtp.login(cfg["user"], cfg["password"])
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(cfg["server"], cfg["port"], timeout=30) as smtp:
                if cfg["user"] and cfg["password"]:
                    smtp.login(cfg["user"], cfg["password"])
                smtp.send_message(msg)
        out["ok"] = True
        out["detail"] = f"sent to {len(recipients)} address(es)"
        logger.info("SOS email sent to %s", recipients)
    except Exception as e:
        out["detail"] = str(e)
        logger.warning("SOS email failed: %s", e)
    return out


def ntfy_topic() -> str:
    return os.environ.get("SOS_NTFY_TOPIC", "").strip()


def _channel_ntfy(body: str, logged_in_username: str, manifest) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": False, "detail": "skipped"}
    topic = ntfy_topic()
    if not topic:
        out["detail"] = "SOS_NTFY_TOPIC not set"
        return out

    url = f"https://ntfy.sh/{urllib.parse.quote(topic, safe='')}"
    title = f"RailMadad SOS · {logged_in_username} · PNR {manifest.pnr}"
    data = body.encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Title": title[:200],
            "Priority": "urgent",
            "Tags": "warning,rail",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            _ = resp.read()
        out["ok"] = True
        out["detail"] = f"ntfy.sh/{topic}"
        logger.info("SOS ntfy topic=%s", topic)
    except urllib.error.HTTPError as e:
        out["detail"] = f"HTTP {e.code}"
        logger.warning("SOS ntfy HTTP %s", e.code)
    except urllib.error.URLError as e:
        out["detail"] = str(e.reason)
        logger.warning("SOS ntfy URL error %s", e.reason)
    return out


def send_sos_notifications(
    manifest,
    logged_in_username: str,
    latitude: float,
    longitude: float,
    accuracy_m: Optional[float],
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Try SMS, WhatsApp, email, ntfy. Success if any channel succeeds.
    Returns (ok, error_message_if_all_failed, payload for JSON).
    """
    phones = sos_phone_destinations()
    body = build_sos_body(
        logged_in_username, manifest, latitude, longitude, accuracy_m
    )
    if os.environ.get("SOS_SMS_LONG", "").strip().lower() in ("1", "true", "yes"):
        sms_body = body[:1500] if len(body) > 1500 else body
    else:
        sms_body = build_sos_sms_body(
            logged_in_username, manifest, latitude, longitude
        )

    planned = (
        (_twilio_credentials() and twilio_sms_from())
        or (_twilio_credentials() and twilio_whatsapp_from())
        or (smtp_config() and bool(sos_email_destinations()))
        or bool(ntfy_topic())
    )
    if not planned:
        return False, (
            "No SOS channel configured. Set any of: TWILIO_PHONE_NUMBER (SMS), "
            "TWILIO_WHATSAPP_FROM (WhatsApp), MAIL_* + SOS_EMAIL_TO (email), "
            "SOS_NTFY_TOPIC (push via ntfy app). See .env.example."
        ), {"channels": {}}

    channels: Dict[str, Any] = {
        "sms": _channel_sms(sms_body, phones),
        "whatsapp": _channel_whatsapp(body, phones),
        "email": _channel_email(
            f"[RailMadad SOS] {logged_in_username} · PNR {manifest.pnr}",
            body,
            logged_in_username,
            manifest,
        ),
        "ntfy": _channel_ntfy(body, logged_in_username, manifest),
    }

    any_ok = any(c.get("ok") for c in channels.values())
    if not any_ok:
        parts = [
            f"{k}: {v.get('detail', '')}"
            for k, v in channels.items()
            if v.get("detail") not in ("skipped", "no SOS_EMAIL_TO", "SOS_NTFY_TOPIC not set")
        ]
        if not parts:
            parts = [f"{k}: {v.get('detail', '')}" for k, v in channels.items()]
        return False, "All channels failed: " + "; ".join(parts)[:800], {"channels": channels}

    summary_parts = []
    if channels["sms"].get("ok"):
        summary_parts.append("SMS")
    if channels["whatsapp"].get("ok"):
        summary_parts.append("WhatsApp")
    if channels["email"].get("ok"):
        summary_parts.append("email")
    if channels["ntfy"].get("ok"):
        summary_parts.append("push (ntfy)")

    payload = {
        "channels": channels,
        "summary": ", ".join(summary_parts),
        "twilio_sms_sid": None,
    }
    sms_msgs = channels["sms"].get("messages") or []
    if sms_msgs:
        payload["twilio_sms_sid"] = sms_msgs[0].get("sid")
        payload["twilio_to"] = sms_msgs[0].get("to")
    wa_msgs = channels["whatsapp"].get("messages") or []
    if wa_msgs:
        payload["twilio_whatsapp_sid"] = wa_msgs[0].get("sid")

    return True, "", payload
