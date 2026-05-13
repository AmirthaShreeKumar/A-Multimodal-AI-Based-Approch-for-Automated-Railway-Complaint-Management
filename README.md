# RailMadad – Railway Complaint Management System

## 📖 Overview
RailMadad is a **web‑based platform** that enables railway passengers and local stakeholders to lodge complaints, provide feedback, and receive timely resolutions. The system harnesses **Gemini AI** and **sentiment analysis** to streamline the handling of diverse inputs (text, audio, images, video) even when connectivity is intermittent. 
---

## 🧩 Core Components
| Component | Description | Key Technologies |
|-----------|-------------|-------------------|
| **app.py** | Flask entry‑point, routes for user actions, login, complaint handling. | Flask, Flask‑Login |
| **ai_engine.py** | Wrapper around Google Gemini API for text generation, classification, and summarisation. | Google Gemini API |
| **ml_sentiment.py** | Offline sentiment analysis using a lightweight Scikit‑learn model; provides urgency scores. | Scikit‑learn, NLTK |
| **Voice Processing** | Captures audio in English; transcribes via Vosk and feeds into AI engine. | Vosk, PyAudio |
| **Static Assets** | CSS, JS, and media handling; graceful degradation when offline. | Bootstrap, vanilla CSS |

---

## 📂 File Overview
Below is a brief description of the key source files in the project:

| File | Purpose |
|------|---------|
| `app.py` | Flask entry‑point, defines routes for complaint handling, authentication, and API endpoints. |
| `ai_engine.py` | Wrapper around Google Gemini API for text generation, classification, and summarisation. |
| `ml_sentiment.py` | Offline sentiment analysis using a lightweight Scikit‑learn model; provides urgency scores. |
| `complaint_analysis.py` | Parses complaint text, extracts entities (e.g., PNR, location) and applies business rules. |
| `classifier.py` | Generic classifier used by `complaint_analysis` to route complaints to appropriate departments. |
| `models/` | Stores trained ML artefacts: `sentiment_model.pkl`, `entity_extractor.pkl`, etc. |
| `sentiment_dataset/` | Contains labelled data used to train the sentiment model (CSV/JSON). |
| `sentiment_model.py` | Training script that builds `sentiment_model.pkl` from `sentiment_dataset`. |
| `sos_notify.py` | Sends high‑priority SOS alerts via **ntfy.sh**; formats message with user & PNR info. |

---

## 🔄 Data Flow
1. **User Input** – The front‑end submits text, image, audio, or video. |
2. **Network Check** – The back‑end determines connectivity:
   - **Online** – Calls `ai_engine` → Gemini cloud service for generation/classification.
   - **Offline** – Falls back to local processing:
     * **Images** → OCR via **Tesseract**.
     * **Audio/Video** → Extraction with **ffmpeg**, then transcription with **Vosk**.
3. **Complaint Analysis** – `complaint_analysis.py` extracts entities and uses `classifier.py` to decide routing.
4. **Sentiment Scoring** – `ml_sentiment.py` (or rule‑based fallback) evaluates urgency.
5. **Result Aggregation** – Combines AI output (if any), extracted entities, and sentiment score into a response stored in SQLite.
6. **Notification** – If the complaint is marked high‑priority, `sos_notify.py` pushes an alert to the **ntfy.sh** channel.
7. **Response** – The Flask API returns a concise summary to the UI.


---

## 🛠️ Technology Stack
- **Backend**: Python (Flask) – Core server-side logic and API routing.

- **Database**: SQLite & SQLAlchemy – Efficient local data storage and ORM.

- **Cloud AI**: Google Gemini Flash – Multimodal analysis for online media processing.

- **Local ML**: Scikit-learn – Sentiment analysis using Logistic Regression & TF-IDF.

- **Offline Audio and Video**: Vosk & FFmpeg – On-device speech-to-text transcription.

- **Offline Image: Tesseract OCR** – Optical character recognition for image data.

- **Dashboard: Chart.js & HTML5** – Interactive data visualization for admin insights.

- **Alerts** : Twilio–SOS alerts (SMS).

- **Styling** : CSS3 (Modern) – Responsive dark-mode UI with rail-inspired aesthetics.


---

## 📦 Setup & Installation
```bash
# Clone repository
git clone <repo-url>
cd railmadad

# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
copy .env.example .env
# Edit .env to add GOOGLE_API_KEY and other secrets

# Initialise the database
python manage.py init-db

# Run the development server
python app.py
```
The app will be reachable at `http://127.0.0.1:5000`.


