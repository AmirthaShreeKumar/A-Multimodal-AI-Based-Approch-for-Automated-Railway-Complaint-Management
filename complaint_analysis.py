"""Normalize AI / fallback output for the Complaint model."""

import os
import re
from typing import Any, Dict, Optional, Tuple

from ai_engine import get_ai_engine
from classifier import classify_with_openai
from ml_sentiment import predict_sentiment


def _norm_priority(p: Any) -> str:
    s = str(p or "").strip().lower()
    if s in ("high", "medium", "low"):
        return s
    if s in ("urgent", "critical"):
        return "high"
    return "medium"


def _from_openai_slug(text: str) -> Dict[str, Any]:
    engine = get_ai_engine()
    oa = classify_with_openai(text)
    if oa:
        dept_slug = oa["department"]
        mapping = {
            "cleanliness": ("Cleanliness", "Housekeeping"),
            "safety": ("Safety", "RPF (Security)"),
            "ticketing": ("Others", "Operations"),
            "catering": ("Food Quality", "Catering"),
            "infrastructure": ("Infrastructure", "Engineering"),
            "staff_behavior": ("Staff Behavior", "HR/Admin"),
            "other": ("Others", "General"),
        }
        cat, dept = mapping.get(dept_slug, ("Others", "General"))
        pri = oa["priority"]
        if isinstance(pri, str):
            pri = pri.title()
        return {
            "category": cat,
            "department": dept,
            "priority": pri if pri in ("High", "Medium", "Low") else "Medium",
            "sentiment": "Neutral",
            "summary": "Classified via OpenAI.",
        }
    has_openai = bool(os.environ.get("OPENAI_API_KEY", "").strip())
    reason = "openai_failed" if has_openai else "no_key"
    return engine.fallback_classification(text, reason=reason)


def analyze_for_complaint(
    text: str,
    image_path: Optional[str] = None,
    audio_path: Optional[str] = None,
    video_path: Optional[str] = None,
) -> Tuple[Dict[str, Any], str]:
    """
    Returns (normalized_fields, short_message_for_flash).
    """
    engine = get_ai_engine()
    has_media = bool(image_path or audio_path or video_path)
    if engine.client:
        raw = engine.analyze_complaint(
            text, image_path, audio_path=audio_path, video_path=video_path
        )
    elif not has_media:
        raw = _from_openai_slug(text)
    else:
        raw = engine.fallback_classification(
            text,
            image_path=image_path,
            audio_path=audio_path,
            video_path=video_path,
            reason="no_key",
        )

    category = str(raw.get("category", "Others")).strip() or "Others"
    department = str(raw.get("department", "General")).strip() or "General"
    priority = _norm_priority(raw.get("priority", "Medium"))
    text_for_sentiment = raw.get("combined_text", text)
    sentiment = predict_sentiment(text_for_sentiment)
    summary = str(raw.get("summary", "")).strip() or "—"

    norm = {
        "category": category[:128],
        "department": department[:256],
        "priority": priority,
        "sentiment": sentiment[:32],
        "summary": summary[:2000],
    }
    dept_short = re.sub(r"\s+", " ", norm["department"])[:80]
    msg = (
        f"{norm['category']} → {dept_short} "
        f"({norm['priority']} priority, {norm['sentiment']})"
    )
    return norm, msg
