import os
import json
import urllib.request
import zipfile
import wave
import subprocess
import imageio_ffmpeg
from pathlib import Path

try:
    import pytesseract
    from PIL import Image
    
    # Configure path based on user installation
    tess_path1 = r'C:\Users\Wissen.2M83NL3\AppData\Local\Programs\Tesseract-OCR\tesseract.exe'
    tess_path2 = r'"C:\Users\Wissen.2M83NL3\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"'
    if os.path.exists(tess_path1):
        pytesseract.pytesseract.tesseract_cmd = tess_path1
    elif os.path.exists(tess_path2):
        pytesseract.pytesseract.tesseract_cmd = tess_path2
        
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

try:
    from vosk import Model, KaldiRecognizer, SetLogLevel
    # AudioSegment from pydub is no longer used, we use ffmpeg directly.
    VOSK_AVAILABLE = True
except ImportError:
    VOSK_AVAILABLE = False

# MoviePy no longer needed as we use ffmpeg directly for video audio extraction.
MOVIEPY_AVAILABLE = True

# Silence Vosk logs
if VOSK_AVAILABLE:
    SetLogLevel(-1)

_BASE_DIR = Path(__file__).resolve().parent
_MODEL_DIR = _BASE_DIR / "vosk-model-small-en-us-0.15"
_MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"

def _get_short_path(path_str):
    """Returns the Windows short path (8.3 name) to handle Unicode issues in C++ libraries like Vosk."""
    if os.name != 'nt':
        return path_str
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(500)
        ctypes.windll.kernel32.GetShortPathNameW(path_str, buf, 500)
        return buf.value or path_str
    except:
        return path_str

def _ensure_vosk_model():
    if _MODEL_DIR.exists():
        return True
    
    zip_path = _BASE_DIR / "vosk_model.zip"
    print(f"Downloading Vosk model for offline speech recognition from {_MODEL_URL}...")
    try:
        urllib.request.urlretrieve(_MODEL_URL, zip_path)
        print("Extracting model...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(_BASE_DIR)
        os.remove(zip_path)
        print("Vosk model ready.")
        return True
    except Exception as e:
        print(f"Failed to download/extract Vosk model: {e}")
        return False

def extract_text_from_image(image_path: str) -> str:
    """Uses Tesseract OCR to extract text from an image."""
    if not OCR_AVAILABLE or not image_path or not os.path.exists(image_path):
        return ""
    try:
        # If tesseract is not in PATH, this will raise an exception.
        text = pytesseract.image_to_string(Image.open(image_path))
        return text.strip()
    except Exception as e:
        print(f"OCR failed for {image_path}: {e}")
        return ""

def transcribe_audio(audio_path: str) -> str:
    """Uses Vosk to transcribe audio to text offline."""
    if not VOSK_AVAILABLE or not audio_path or not os.path.exists(audio_path):
        return ""
        
    if not _ensure_vosk_model():
        return ""

    temp_wav = _BASE_DIR / "temp_audio_for_vosk.wav"
    try:
        # Use subprocess with the bundled ffmpeg from imageio-ffmpeg.
        # This avoids pydub's dependency on ffprobe which causes [WinError 2] on Windows.
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        
        command = [
            ffmpeg_exe,
            "-y",
            "-i", audio_path,
            "-ar", "16000",
            "-ac", "1",
            str(temp_wav)
        ]
        
        # Run conversion
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Use short path to handle Unicode characters in the folder path (e.g. Japanese characters)
        model_path = _get_short_path(str(_MODEL_DIR))
        model = Model(model_path)
        wf = wave.open(str(temp_wav), "rb")
        rec = KaldiRecognizer(model, wf.getframerate())

        results = []
        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break
            if rec.AcceptWaveform(data):
                res = json.loads(rec.Result())
                if 'text' in res:
                    results.append(res['text'])
        
        final_res = json.loads(rec.FinalResult())
        if 'text' in final_res:
            results.append(final_res['text'])
            
        return " ".join(results).strip()
    except Exception as e:
        print(f"Audio transcription failed for {audio_path}: {e}")
        return ""
    finally:
        if temp_wav.exists():
            try:
                os.remove(temp_wav)
            except:
                pass

def extract_audio_from_video(video_path: str) -> str:
    """Extracts audio from video and transcribes it."""
    if not video_path or not os.path.exists(video_path):
        return ""

    # ffmpeg handles video files as input and extracts the audio track automatically.
    return transcribe_audio(video_path)
