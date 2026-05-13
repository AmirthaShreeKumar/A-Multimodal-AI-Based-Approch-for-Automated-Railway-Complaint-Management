import json
import os
import re
from typing import Optional, TypedDict

DEPARTMENTS = [
    "cleanliness",
    "safety",
    "ticketing",
    "catering",
    "infrastructure",
    "staff_behavior",
    "other",
]


class Classification(TypedDict):
    department: str
    priority: str


def _normalize_department(value: str) -> str:
    v = (value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if v in DEPARTMENTS:
        return v
    mapping = {
        "clean": "cleanliness",
        "hygiene": "cleanliness",
        "ticket": "ticketing",
        "booking": "ticketing",
        "food": "catering",
        "pantry": "catering",
        "platform": "infrastructure",
    }
    return mapping.get(v, "other")


def _normalize_priority(value: str) -> str:
    v = (value or "").strip().lower()
    if v in ("low", "medium", "high"):
        return v
    if v in ("urgent", "critical", "severe"):
        return "high"
    if v in ("normal", "moderate"):
        return "medium"
    return "medium"


def classify_with_keywords(text: str) -> Classification:
    t = text.lower()
    dept = "other"
    priority = "medium"

    if any(
        w in t
        for w in (
            "dirty",
            "clean",
            "toilet",
            "washroom",
            "garbage",
            "litter",
            "hygiene",
        )
    ):
        dept = "cleanliness"
    elif any(
        w in t
        for w in (
            "unsafe",
            "safety",
            "accident",
            "fire",
            "emergency",
            "theft",
            "harass",
        )
    ):
        dept = "safety"
    elif any(
        w in t
        for w in (
            "ticket",
            "booking",
            "refund",
            "tatkal",
            "pnr",
            "reservation",
        )
    ):
        dept = "ticketing"
    elif any(
        w in t
        for w in ("food", "meal", "catering", "pantry", "water", "tea", "coffee")
    ):
        dept = "catering"
    elif any(
        w in t
        for w in (
            "platform",
            "bridge",
            "escalator",
            "lift",
            "roof",
            "track",
            "station building",
        )
    ):
        dept = "infrastructure"
    elif any(
        w in t
        for w in ("staff", "rude", "behavior", "tc", "tt", "inspector", "employee")
    ):
        dept = "staff_behavior"

    if any(w in t for w in ("urgent", "emergency", "danger", "unsafe", "immediate")):
        priority = "high"
    elif any(w in t for w in ("minor", "small", "suggestion")):
        priority = "low"

    return {"department": dept, "priority": priority}


def classify_with_gemini(text: str) -> Optional[Classification]:
    api_key = (
        os.environ.get("GOOGLE_API_KEY", "").strip()
        or os.environ.get("GEMINI_API_KEY", "").strip()
    )
    if not api_key:
        return None

    try:
        import google.generativeai as genai
    except ImportError:
        return None

    dept_list = ", ".join(DEPARTMENTS)
    model_name = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
    prompt = f"""You classify Indian Railways passenger grievances for RailMadad.
Given the complaint text, respond with ONLY a JSON object with keys:
- "department": one of [{dept_list}]
- "priority": one of low, medium, high

Complaint:
{text.strip()[:4000]}
"""

    def _parse_json_response(raw: str) -> Optional[Classification]:
        raw = raw.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return {
            "department": _normalize_department(str(data.get("department", "other"))),
            "priority": _normalize_priority(str(data.get("priority", "medium"))),
        }

    try:
        genai.configure(api_key=api_key)
        gcfg = genai.GenerationConfig(
            temperature=0.2,
            max_output_tokens=128,
            response_mime_type="application/json",
        )
        model = genai.GenerativeModel(model_name, generation_config=gcfg)
        resp = model.generate_content(prompt)
        raw = (resp.text or "").strip()
        parsed = _parse_json_response(raw)
        if parsed:
            return parsed
    except Exception:
        pass

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        resp = model.generate_content(prompt)
        return _parse_json_response(resp.text or "")
    except Exception:
        return None


def classify_with_openai(text: str) -> Optional[Classification]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    try:
        from openai import OpenAI
    except ImportError:
        return None

    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    client = OpenAI(api_key=api_key)
    dept_list = ", ".join(DEPARTMENTS)

    prompt = f"""You classify Indian Railways passenger grievances for RailMadad.
Given the complaint text, respond with ONLY a JSON object (no markdown) with keys:
- "department": one of [{dept_list}]
- "priority": one of low, medium, high

Complaint:
{text.strip()[:4000]}
"""

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You output only valid JSON with keys department and priority.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=120,
        )
        raw = (resp.choices[0].message.content or "").strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        return {
            "department": _normalize_department(str(data.get("department", "other"))),
            "priority": _normalize_priority(str(data.get("priority", "medium"))),
        }
    except Exception:
        return None


def classify_complaint(text: str) -> Classification:
    if not text or not text.strip():
        return {"department": "other", "priority": "low"}
    gemini = classify_with_gemini(text)
    if gemini:
        return gemini
    ai = classify_with_openai(text)
    if ai:
        return ai
    return classify_with_keywords(text)
