import json
import mimetypes
import os
import re
import time
from typing import Any, Dict, List, Optional

from PIL import Image

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:
    genai = None  # type: ignore
    genai_types = None  # type: ignore

# Browser voice clips are small; inline avoids File API edge cases (missing uri, etc.).
_MAX_INLINE_AUDIO_BYTES = 8 * 1024 * 1024


def _guess_mime(path: str, *, prefer_audio: bool = False) -> str:
    mime, _ = mimetypes.guess_type(path)
    if mime:
        return mime
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    audio = {
        "webm": "audio/webm",
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "m4a": "audio/mp4",
        "ogg": "audio/ogg",
        "flac": "audio/flac",
        "aac": "audio/aac",
        "mp4": "audio/mp4",
    }
    video = {
        "mp4": "video/mp4",
        "webm": "video/webm",
        "mov": "video/quicktime",
        "mpeg": "video/mpeg",
        "mpg": "video/mpeg",
    }
    if prefer_audio:
        return audio.get(ext, video.get(ext, "application/octet-stream"))
    return video.get(ext, audio.get(ext, "application/octet-stream"))


def _api_key() -> str:
    k = (
        os.environ.get("GOOGLE_API_KEY", "").strip()
        or os.environ.get("GEMINI_API_KEY", "").strip()
    )
    if len(k) >= 2 and k[0] == k[-1] and k[0] in "\"'":
        k = k[1:-1].strip()
    return k


def _strip_json_fence(raw: str) -> str:
    s = raw.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)
    return s.strip()


class AI_Engine:
    """Gemini client (google.genai) for complaint analysis, chat, and optional media."""

    def __init__(self) -> None:
        key = _api_key()
        self.client = None
        if key and genai is not None:
            try:
                self.client = genai.Client(api_key=key)
            except Exception as e:
                print(f"RailMadad: Gemini Client() failed ({e}). Check GOOGLE_API_KEY.")
                self.client = None
        # Models with strong audio/video multimodal first (short voice clips use inline bytes).
        self.models_to_try = [
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-1.5-flash",
            "gemini-1.5-pro",
            "gemini-2.0-flash-exp",
            "gemini-2.5-pro",
        ]

    def _upload_and_wait(self, path: str, label: str) -> Optional[Any]:
        if not self.client or not path:
            return None
        try:
            uploaded = self.client.files.upload(file=path)
            while uploaded.state.name == "PROCESSING":
                time.sleep(2)
                uploaded = self.client.files.get(name=uploaded.name)
            if uploaded.state.name == "FAILED":
                print(f"{label} processing failed")
                return None
            return uploaded
        except Exception as e:
            print(f"Error uploading {label}: {e}")
            return None

    def _parts_for_audio(self, audio_path: str) -> List[Any]:
        """Inline bytes first (reliable for short mic recordings); else File API + Part.from_uri."""
        if not genai_types or not self.client:
            return []
        out: List[Any] = []
        try:
            sz = os.path.getsize(audio_path)
        except OSError as e:
            print(f"RailMadad: cannot read audio file: {e}")
            return []
        if sz == 0:
            print("RailMadad: empty audio upload")
            return []

        mime = _guess_mime(audio_path, prefer_audio=True)
        if not mime.startswith("audio/"):
            if audio_path.lower().endswith(".webm"):
                mime = "audio/webm"
            elif audio_path.lower().endswith(".mp4"):
                mime = "audio/mp4"
            else:
                mime = "audio/mpeg"

        if sz <= _MAX_INLINE_AUDIO_BYTES:
            try:
                with open(audio_path, "rb") as f:
                    data = f.read()
                out.append(genai_types.Part.from_bytes(data=data, mime_type=mime))
                out.append(
                    "Audio above: passenger voice recording — listen and classify the grievance from what they say."
                )
                return out
            except Exception as e:
                print(f"RailMadad: inline audio failed, trying File API: {e}")

        fh = self._upload_and_wait(audio_path, "Audio")
        if fh and fh.uri and fh.mime_type:
            out.append(
                genai_types.Part.from_uri(file_uri=fh.uri, mime_type=fh.mime_type)
            )
            out.append(
                "Audio file above: passenger voice — listen and classify the grievance."
            )
            return out
        if fh:
            print(
                f"RailMadad: audio File API object missing uri/mime (state={fh.state}). Voice not sent to model."
            )
        return []

    def _parts_for_video(self, video_path: str) -> List[Any]:
        if not genai_types or not self.client:
            return []
        fh = self._upload_and_wait(video_path, "Video")
        if not fh or not fh.uri or not fh.mime_type:
            if fh:
                print(
                    f"RailMadad: video File API missing uri/mime (state={fh.state}). Video not sent."
                )
            return []
        return [
            genai_types.Part.from_uri(file_uri=fh.uri, mime_type=fh.mime_type),
            "Video above: use visible and audible content to classify the grievance.",
        ]

    def analyze_complaint(
        self,
        text: str,
        image_path: Optional[str] = None,
        audio_path: Optional[str] = None,
        video_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.client:
            return self.fallback_classification(
                text,
                image_path=image_path,
                audio_path=audio_path,
                video_path=video_path,
                reason="no_key",
            )

        # Media first, then instructions — improves multimodal understanding.
        prompt_parts: List[Any] = []

        if image_path:
            try:
                prompt_parts.append(Image.open(image_path))
                prompt_parts.append(
                    "Image above: railway-related grievance evidence — use what you see."
                )
            except Exception as e:
                print(f"Error loading image: {e}")

        if audio_path:
            prompt_parts.extend(self._parts_for_audio(audio_path))

        if video_path:
            prompt_parts.extend(self._parts_for_video(video_path))

        written = text.strip()
        if written:
            prompt_parts.append(f"Written complaint from passenger:\n{written}")
        else:
            prompt_parts.append(
                "The passenger did not type a description. Use only the image/audio/video "
                "parts above (do not claim that no media was provided if audio or video is above)."
            )

        prompt_parts.append(
            "You classify Indian Railways RailMadad grievances. "
            "Categories: Cleanliness, Infrastructure, Safety, Staff Behavior, Food Quality, "
            "Delays, Medical Emergency, Others. "
            "Departments: Housekeeping, Engineering, RPF (Security), HR/Admin, Catering, "
            "Operations, Medical, General. "
            "Priority: High, Medium, Low (safety, medical, harassment → High). "
            "Sentiment: Positive, Neutral, Negative. "
            'Output valid JSON only: {"category":"","department":"","priority":"","sentiment":"","summary":""}. '
            "Summary: what happened according to text and/or what you hear or see in media — "
            "not meta-commentary about the form."
        )

        for model_name in self.models_to_try:
            try:
                response = self.client.models.generate_content(
                    model=model_name,
                    contents=prompt_parts,
                )
                json_str = _strip_json_fence(response.text or "")
                result = json.loads(json_str)
                return result
            except Exception as e:
                print(f"Model {model_name} failed: {e}")

        print("All AI models failed. Using rule-based fallback.")
        return self.fallback_classification(
            text,
            image_path=image_path,
            audio_path=audio_path,
            video_path=video_path,
            reason="api_failed",
        )

    def fallback_classification(
        self,
        text: str,
        image_path: Optional[str] = None,
        audio_path: Optional[str] = None,
        video_path: Optional[str] = None,
        reason: str = "keyword",
    ) -> Dict[str, Any]:
        media_text = ""
        if image_path:
            try:
                from offline_media import extract_text_from_image
                extracted = extract_text_from_image(image_path)
                if extracted:
                    media_text += " " + extracted
            except ImportError:
                pass
                
        if audio_path:
            try:
                from offline_media import transcribe_audio
                extracted = transcribe_audio(audio_path)
                if extracted:
                    media_text += " " + extracted
            except ImportError:
                pass
                
        if video_path:
            try:
                from offline_media import extract_audio_from_video
                extracted = extract_audio_from_video(video_path)
                if extracted:
                    media_text += " " + extracted
            except ImportError:
                pass

        if media_text:
            text += " " + media_text.strip()

        text_lower = text.lower()
        category = "Others"
        department = "General"
        priority = "Medium"
        if reason == "no_key":
            summary_note = (
                "Set GOOGLE_API_KEY in your .env file to use Gemini. "
                "Right now this was sorted with keyword rules only. "
            )
        elif reason == "api_failed":
            summary_note = (
                "Gemini did not return a usable answer (model or network issue). "
                "Keyword rules were used instead. "
            )
        elif reason == "openai_failed":
            summary_note = (
                "OpenAI was not configured or did not respond; keyword rules used. "
            )
        else:
            summary_note = "Classified with keyword rules. "

        if any(
            w in text_lower
            for w in (
                "dirty", "garbage", "dust", "toilet", "washroom", "clean", "smell", "stink", 
                "waste", "litter", "unhygienic", "mess", "floor", "ganda", "kachra", "kuppai", "shauchalay"
            )
        ):
            category = "Cleanliness"
            department = "Housekeeping"
        elif any(
            w in text_lower
            for w in (
                "broken", "light", "fan", "ac", "charging", "seat", "escalator", "window", 
                "door", "leak", "tap", "switch", "button", "handle", "berth", "pankha", "khidki"
            )
        ):
            category = "Infrastructure"
            department = "Engineering"
        elif any(
            w in text_lower
            for w in (
                "theft", "steal", "fight", "harass", "safe", "security", "rob", "pickpocket", 
                "threat", "dangerous", "help", "alarm", "police", "rpf", "chor", "chori", "bachao"
            )
        ):
            category = "Safety"
            department = "RPF (Security)"
            priority = "High"
        elif any(
            w in text_lower 
            for w in (
                "food", "stale", "water", "pantry", "tea", "meal", "lunch", "dinner", 
                "breakfast", "coffee", "taste", "bad", "cold", "khana", "paani", "sappad"
            )
        ):
            category = "Food Quality"
            department = "Catering"
        elif any(
            w in text_lower 
            for w in (
                "rude", "staff", "tt", "tte", "behavior", "shouting", "arguing", 
                "unhelpful", "arrogant", "officer", "badtameez"
            )
        ):
            category = "Staff Behavior"
            department = "HR/Admin"
        elif any(
            w in text_lower 
            for w in (
                "health", "sick", "doctor", "medical", "emergency", "pain", "hospital", 
                "ambulance", "injury", "blood", "beemar", "dard"
            )
        ):
            category = "Medical Emergency"
            department = "Medical"
            priority = "High"
        elif any(
            w in text_lower 
            for w in ("delay", "late", "timing", "cancel", "postpone", "deri", "late")
        ):
            category = "Delays"
            department = "Operations"
        elif any(
            w in text_lower
            for w in (
                "stampede", "crush", "trampled", "mob", "panic", "unsafe crowd", "bheed"
            )
        ):
            category = "Safety"
            department = "RPF (Security)"
            priority = "High"
        elif any(
            w in text_lower
            for w in (
                "crowd", "crowded", "crowed", "overcrowd", "over crow", "overcrowding",
                "too many people", "pushing", "shoving", "queue", "long line", "waiting hall packed"
            )
        ):
            category = "Others"
            department = "Operations"

        if not text.strip():
            if image_path or audio_path or video_path:
                summary_note += "Media evidence attached. "
            else:
                summary_note += "No details provided."
        else:
            summary_note += f" Auto-classified from: \"{text[:100]}...\""

        return {
            "category": category,
            "department": department,
            "priority": priority,
            "sentiment": "Neutral",
            "summary": summary_note,
            "combined_text": text.strip(),
        }

    def chatbot_response(self, user_message: str) -> str:
        if not self.client:
            return (
                "I cannot reach the AI server right now. Use Register → User login → "
                "Dashboard → New Complaint to file a grievance."
            )
        prompt = (
            "You are RailAssist, the smart assistant for this railway complaint website. "
            "Your job is to guide users on how to use THIS website to resolve issues. "
            "To file a complaint, tell them to: 1. Login/Register. 2. Go to their Dashboard. "
            "3. Use the New Complaint form. "
            "Do not give generic advice about calling numbers unless it is a medical emergency. "
            "Keep your answer under 2-3 sentences. "
            f"User asks: '{user_message}'"
        )
        for model_name in self.models_to_try:
            try:
                response = self.client.models.generate_content(
                    model=model_name,
                    contents=[prompt],
                )
                return (response.text or "").strip() or "No response."
            except Exception as e:
                print(f"Chatbot model {model_name} failed: {e}")
        return "I am currently unable to connect to the AI server. Please try again later."

    def analyze_sentiment(self, text: str) -> str:
        res = self.analyze_complaint(text)
        return str(res.get("sentiment", "Neutral"))

    def verify_faces(self, path1: str, path2: str) -> Dict[str, Any]:
        if not self.client:
            return {
                "match": False,
                "confidence": "Low",
                "reason": "AI client not configured",
            }
        try:
            img1 = Image.open(path1)
            img2 = Image.open(path2)
            prompt: List[Any] = [
                "You are a biometric verification AI.",
                "Compare the two faces in these images.",
                "Are they the same person?",
                "Consider facial features, bone structure, and landmarks.",
                "Ignore lighting, age differences (if minor), or accessories like glasses.",
                "Return a JSON object ONLY: {'match': boolean, 'confidence': 'High/Medium/Low', 'reason': 'brief explanation'}",
                img1,
                "Reference Image",
                img2,
                "Live Capture Image",
            ]
            for model_name in self.models_to_try:
                try:
                    response = self.client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                    )
                    json_str = _strip_json_fence(response.text or "")
                    return json.loads(json_str)
                except Exception as e:
                    print(f"Face verification model {model_name} failed: {e}")
            return {"match": False, "confidence": "Low", "reason": "AI processing failed"}
        except Exception as e:
            print(f"Verification error: {e}")
            return {"match": False, "confidence": "Low", "reason": "Image error"}


_engine: Optional[AI_Engine] = None


def get_ai_engine() -> AI_Engine:
    global _engine
    if _engine is None:
        _engine = AI_Engine()
    return _engine
