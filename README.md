# 🚆 RailMadad Passenger Grievance System

**A production-ready, highly resilient web platform designed to handle railway passenger grievances using AI-driven multimodal analysis (Text, Images, Audio, Video), complete with offline fallbacks and regional sentiment classification.**

---

## 📖 Overview
RailMadad is built to streamline the handling of diverse passenger inputs even when connectivity is intermittent. It uses **Google Gemini 2.5** for high-end online multimodal classification and falls back to **Tesseract OCR** and **Vosk Speech-to-Text** when offline. The system is fortified with a 12-point production readiness framework to ensure absolute security, reliability, and low latency.

---

## 🏛️ Detailed Architecture Diagram

The system employs a layered architecture that safely intercepts, validates, and processes inputs before routing them to the AI engine or the offline fallback logic.


![System Architecture](Architecture.png)
    


### 🧩 Core System Modules:
1.  **Module 1: User Auth & PNR Verification**: Handles passenger sign-ins and verifies live train journey details using PNR.
2.  **Module 2: User Input & Complaint Submission**: The UI interface allowing users to upload text and media.
3.  **Module 3: Multimodal Processing**: Ingests Text, Image, Audio, and Video files for parsing.
4.  **Module 4 & 5: Classification & Sentiment Analysis**: Extracts the core issue and evaluates passenger sentiment (Positive/Neutral/Negative).
5.  **Module 6: Complaint Routing**: Identifies the exact department (Cleanliness, Security, Ticketing, Catering, etc.) responsible.
6.  **Module 7: Urgency Detection**: Combines department type and sentiment to assign High 🔴, Medium 🟡, or Low 🟢 Priority.
7.  **Module 8: SOS Emergency Module**: Instantly triggers Twilio/ntfy SMS alerts for medical or security emergencies (Bypasses Database for immediate dispatch).
8.  **Module 9: Fallback Mechanism**: Triggers local OCR (Tesseract) and Speech-to-Text (Vosk) when internet access is down.
9.  **Production Additions**: A Rate Limiter, Safety Interceptor, Pydantic validator, and `app.log` centralized logger ensure enterprise-grade security.

### 🛡️ Admin Dashboard
The system includes a dedicated Admin portal (`/login/admin`) equipped with several powerful staff tools:
*   **Active Queue**: View all incoming passenger complaints grouped by priority (High/Medium/Low) in real-time.
*   **Resolution Workflow**: Staff can review AI-generated summaries, view attached evidence, and update ticket statuses to `Resolved`.
*   **Manifest Management**: Admins can securely upload or edit the Passenger Manifest, ensuring only legitimate ticketholders can file complaints.
*   **Insights & Analytics**: A comprehensive data page showing sentiment distribution, feedback ratings, and overall resolution rates.

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

## 📝 Example Inputs & Media Testing

### 📝 Testing Text & Voice Analysis
*   **Sample Text Input**: "The AC in coach B2 is not working and the washrooms on platform 4 need cleaning."
*   **Voice Input**: You can just record audio for voice directly using the microphone button on the dashboard.

### 📷🎥 Testing Image & Video Analysis
*   **Sample Media**: You can also try with images and videos in the `Sample_inputs` folder to see how the multimodal AI extracts context and determines the priority level.
*   **Persistent Cache**: The system now uses an `ai_cache.json` file to store hashed inputs and their classification results, enabling fast reuse of previous AI responses and reducing API costs.

---

## 🏆 The 12-Point Production Checklist Compliance

This project has been heavily audited and hardened to meet strict production-readiness standards.

1.  **Deterministic Safety Interceptor**: A `SafetyInterceptor` in `ai_engine.py` blocks SQL injection patterns, script injection vectors, PII (e.g., credit cards), and irrelevant non-railway inputs before hitting the LLM.
2.  **Asynchronous AI Clients**: Uses asynchronous client instances (`self.client.aio.models.generate_content`) to prevent blocking the main Flask thread during high traffic.
3.  **Strict Schema Validation (Pydantic)**: Uses Pydantic (`schemas.py`) to enforce strict JSON output from the AI (via `response_schema`), guaranteeing that database inserts never fail due to bad formatting.
4.  **Shared Secret Credentials**: Uses an `APP_AI_SECRET` handshake in `.env` to reject direct API abuse and prevent bad actors from burning through AI credits.
5.  **Silent Error Handlers (No Leakage)**: Try-except blocks catch fatal errors and flash generic, polite messages to users, hiding all technical stack traces and database paths.
6.  **Off-Memory State Persistence**: All user sessions, manifest logic, feedback logs, and complaint queues are safely persisted in PostgreSQL/SQLite using SQLAlchemy.
7.  **Agent Loop Safeguards**: The multimodal pipelines run on a strict single-pass loop. There are no cascading multi-agent conversations that can get stuck in infinite, expensive loops.
8.  **Context Window Management**: The chatbot is turn-optimized, and AI instructions demand concise, 2-3 sentence summaries to keep token usage consistently low.
9.  **Sliding-Window Rate Limiting**: The `@limit_ai` decorator uses a thread-safe queue in `rate_limiter.py` to throttle incoming POST requests to **5 calls per minute per IP**.
10. **Sanitized SQL Queries**: 100% of database queries use SQLAlchemy's built-in parameterization and ORM abstractions, making SQL injection impossible.
11. **Old Media File Purging**: The `cleanup.py` script automatically runs on startup, deleting uploaded media in `instance/uploads` that is older than 24 hours to prevent disk exhaustion.
12. **Singleton / Dependency Injection**: `get_ai_engine()` acts as a global Singleton registry, guaranteeing only one heavy AI API client is instantiated and reused globally.

---

## 🪵 Production Logging System

All system events, audit trails, and caught exceptions are saved to a dedicated, centralized log file for observability:
📂 **`app.log`**

*   **Security Events**: Triggers a `WARNING` entry with the attacker's IP if an unauthorized script attempts to bypass the UI forms.
*   **Audit Trail**: Logs an `INFO` entry when a complaint is successfully stored.
*   **Fatal Errors**: Captures the full technical traceback inside `app.log` (away from user eyes) whenever an exception is caught.

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
# Edit .env to add GOOGLE_API_KEY, APP_AI_SECRET, etc.

# Run the production-ready server (Debug is ON but Reloader is OFF to prevent crash loops)
python app.py
```
The app will be reachable at `http://127.0.0.1:5000`.
