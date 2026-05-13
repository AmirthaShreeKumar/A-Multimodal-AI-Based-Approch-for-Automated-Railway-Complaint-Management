# RailMadad – Comprehensive Project Overview (Hybrid AI)


## 🎯 Project Goal
RailMadad is a **Hybrid AI grievance handling system** designed for Indian Railways. It leverages state‑of‑the‑art **Multimodal LLMs (Gemini)** as the primary intelligence engine, while providing a **robust offline fallback mechanism** using local ML models to ensure 100% availability even in signal‑less train environments.

---

## 🏗️ Architecture Diagram
`	ext
            +-----------------------+
            |    PASSENGER INPUT    |
            | (Text, Image, Audio)  |
            +----------+------------+
                       |
                       v
            +----------+------------+
            | LOCAL MEDIA EXTRACTION|
            |  (Tesseract / Vosk)   |
            +----------+------------+
                       |
          /------------+------------\
          |                         |
          v                         v
    [ PRIMARY PATH ]          [ FALLBACK PATH ]
    (Gemini Online)           (Keyword Offline)
          |                         |
          \------------+------------/
                       |
                       v
            +----------+------------+
            | LOCAL SENTIMENT AI    |
            | (Scikit-Learn Model)  |
            +----------+------------+
                       |
                       v
            +----------+------------+
            |   SQLITE DATABASE     |
            |  (Local Storage)      |
            +----------+------------+
                       |
                       v
            +----------+------------+
            |   ADMIN DASHBOARD     |
            |  (Charts & Insights)  |
            +-----------------------+
`

## 🔄 System Flow
1. **Input Capture:** User submits a grievance via the web portal (supports Multimodal inputs).
2. **Extraction:** Local engines (Tesseract/Vosk) extract text from media immediately.
3. **Branching:** System checks for Google API connectivity.
4. **Processing:**
    - **Primary:** Gemini Flash analyzes raw media + text for high-fidelity classification.
    - **Fallback:** Rule-based engine scans extracted text for critical keywords.
5. **Sentiment Scoring:** A local Logistic Regression model calculates passenger emotion (Positive/Neutral/Negative).
6. **Storage & Alert:** Data is saved to SQLite; SOS triggers are sent for High-Priority cases.
7. **Insights:** Admin views real-time statistics and visualizations on the dashboard.

---

## 1️⃣ Execution Entry Point – pp.py
- **Flask Server** – Boots the system and handles routing.
- **SQLite DB (ailmadad.db)** – A local, persistent store that captures all data locally first.
- **AI Engine Init** – Readies the **Gemini 1.5/2.0 Flash** models if a GOOGLE_API_KEY is present.

---

## 2️⃣ Primary Intelligence vs. Fallback Logic
The system prioritizes high‑accuracy cloud AI but switches automatically if the network fails:

### 🔵 Primary Path: Gemini Multimodal (Online)
- **Engine:** Gemini Flash 1.5 / 2.0.
- **Capability:** Directly "sees" photos and "hears" audio files to understand complex context, sarcasm, or visual damage.
- **Outcome:** Highly nuanced classification and summaries.

### ⚪ Fallback Path: Keyword & Local Engines (Offline)
- **Engine:** Local Keyword Engine + offline_media.py.
- **Capability:** Uses **Tesseract OCR** for images and **Vosk** for audio to convert media to text, then scans for pre‑defined safety/facility keywords.
- **Outcome:** Reliable categorization and prioritization when disconnected.

---

## 3️⃣ Media Processing Breakdown
| Media Type | Extraction Tool | Primary (Online) | Fallback (Offline) |
|------------|-----------------|------------------|--------------------|
| **Image**  | Tesseract OCR   | Gemini Vision    | Keyword Match      |
| **Audio**  | Vosk STT        | Gemini Audio     | Keyword Match      |
| **Video**  | FFmpeg          | Gemini Video     | Audio Transcription|

---

## 4️⃣ Sentiment Analysis – ml_sentiment.py
Unlike classification, sentiment is **always processed locally** to ensure privacy and speed:
- **Model:** Logistic Regression (Scikit‑Learn).
- **Vectorization:** TF‑IDF.
- **Fallback:** Uses the passenger's **Star Rating** (1‑5) for high‑confidence sentiment when text is too brief.

---

## 5️⃣ Fail‑Safe / Offline Toolchain
- **Vosk:** Lightweight acoustic model for on‑device speech recognition.
- **Tesseract:** Local OCR for digitizing text from photos.
- **FFmpeg:** Local media processing to handle various video formats.

---

## 6️⃣ Admin Dashboard – “The Brain”
- **Local Visualization:** Chart.js (locally served) generates sentiment and department distribution charts.
- **Audit Trail:** Specifically displays the **"Extracted Text"** so admins can see exactly what the fallback AI parsed during a signal outage.

---

## 7️⃣ Technology Stack Summary
- **Primary AI:** Google Gemini Multimodal.
- **Fallback AI:** Vosk (STT), Tesseract (OCR), Keyword Engine.
- **ML Engine:** Scikit‑learn (Sentiment Analysis).
- **Backend:** Flask, Python 3.11, SQLite.
- **Frontend:** HTML5, CSS3 (Vanilla), JavaScript, Chart.js.
