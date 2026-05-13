import json
import os
import secrets
import time
import uuid
import warnings
from collections import Counter
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

warnings.filterwarnings(
    "ignore",
    message=".*Python version 3.9 past its end of life.*",
    category=FutureWarning,
)
warnings.filterwarnings("ignore", message=".*urllib3 v2 only supports OpenSSL.*")

_BASE = Path(__file__).resolve().parent
load_dotenv(_BASE / ".env")
load_dotenv()

from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from sqlalchemy import func, inspect
from sqlalchemy.orm import joinedload
from werkzeug.utils import secure_filename

from ai_engine import _api_key, get_ai_engine
from complaint_analysis import analyze_for_complaint
from models import Complaint, EligiblePassenger, Feedback, User, db
from sos_notify import send_sos_notifications

SOS_COOLDOWN_SEC = 90

BASE_DIR = _BASE
UPLOAD_DIR = BASE_DIR / "instance" / "uploads"
ALLOWED_IMAGE_EXT = frozenset({"png", "jpg", "jpeg", "gif", "webp"})
ALLOWED_AUDIO_EXT = frozenset(
    {"mp3", "wav", "m4a", "webm", "ogg", "flac", "aac", "mp4"}
)
ALLOWED_VIDEO_EXT = frozenset({"mp4", "webm", "mov", "mpeg", "mpg"})


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get(
        "SECRET_KEY", "dev-change-me-in-production"
    )
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'railmadad.db'}"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024

    db.init_app(app)

    with app.app_context():
        db.create_all()
        _migrate_complaints_schema()
        _migrate_feedback_schema()
        _migrate_complaints_booking_columns()
        _migrate_eligible_passengers_phone()
        _migrate_complaints_booking_phone()
        _ensure_admin()

    env_path = BASE_DIR / ".env"
    key_loaded = bool(_api_key())
    eng = get_ai_engine()
    if eng.client:
        print("RailMadad: Gemini client ready (GOOGLE_API_KEY loaded).")
    else:
        if not env_path.is_file():
            print(
                f"RailMadad: No .env file at {env_path}\n"
                "  → Copy .env.example to .env, add GOOGLE_API_KEY=your-key, save, restart."
            )
        elif not key_loaded:
            print(
                f"RailMadad: {env_path} exists but GOOGLE_API_KEY / GEMINI_API_KEY is empty.\n"
                "  → Open .env and set: GOOGLE_API_KEY=AIza... (one line, no spaces around =)."
            )
        else:
            print(
                "RailMadad: Key is set but Gemini client is still off.\n"
                "  → Check the 'Client() failed' message above, or rotate your API key in Google AI Studio."
            )
        print("  → Optional text-only fallback: OPENAI_API_KEY in .env")

    register_routes(app)
    return app


def _migrate_complaints_schema() -> None:
    """Add new columns for existing SQLite databases."""
    try:
        insp = inspect(db.engine)
        if "complaints" not in insp.get_table_names():
            return
        existing = {c["name"] for c in insp.get_columns("complaints")}
        statements = []
        if "category" not in existing:
            statements.append(
                "ALTER TABLE complaints ADD COLUMN category VARCHAR(128) DEFAULT 'Others'"
            )
        if "sentiment" not in existing:
            statements.append(
                "ALTER TABLE complaints ADD COLUMN sentiment VARCHAR(32) DEFAULT 'Neutral'"
            )
        if "summary" not in existing:
            statements.append("ALTER TABLE complaints ADD COLUMN summary TEXT")
        if "attachments_json" not in existing:
            statements.append("ALTER TABLE complaints ADD COLUMN attachments_json TEXT")
        for sql in statements:
            try:
                db.session.execute(db.text(sql))
                db.session.commit()
            except Exception:
                db.session.rollback()
    except Exception:
        pass


def _migrate_feedback_schema() -> None:
    try:
        insp = inspect(db.engine)
        if "feedbacks" not in insp.get_table_names():
            return
        existing = {c["name"] for c in insp.get_columns("feedbacks")}
        if "sentiment" not in existing:
            try:
                db.session.execute(db.text("ALTER TABLE feedbacks ADD COLUMN sentiment VARCHAR(32)"))
                db.session.commit()
            except Exception:
                db.session.rollback()
    except Exception:
        pass


def _migrate_complaints_booking_columns() -> None:
    try:
        insp = inspect(db.engine)
        if "complaints" not in insp.get_table_names():
            return
        existing = {c["name"] for c in insp.get_columns("complaints")}
        alters = [
            ("booking_pnr", "ALTER TABLE complaints ADD COLUMN booking_pnr VARCHAR(32)"),
            (
                "booking_train",
                "ALTER TABLE complaints ADD COLUMN booking_train VARCHAR(256)",
            ),
            (
                "booking_location",
                "ALTER TABLE complaints ADD COLUMN booking_location VARCHAR(256)",
            ),
            ("booking_seat", "ALTER TABLE complaints ADD COLUMN booking_seat VARCHAR(64)"),
            (
                "booking_email",
                "ALTER TABLE complaints ADD COLUMN booking_email VARCHAR(256)",
            ),
        ]
        for col, sql in alters:
            if col not in existing:
                try:
                    db.session.execute(db.text(sql))
                    db.session.commit()
                except Exception:
                    db.session.rollback()
    except Exception:
        pass


def _migrate_complaints_booking_phone() -> None:
    try:
        insp = inspect(db.engine)
        if "complaints" not in insp.get_table_names():
            return
        existing = {c["name"] for c in insp.get_columns("complaints")}
        if "booking_phone" not in existing:
            try:
                db.session.execute(
                    db.text(
                        "ALTER TABLE complaints ADD COLUMN booking_phone VARCHAR(32)"
                    )
                )
                db.session.commit()
            except Exception:
                db.session.rollback()
    except Exception:
        pass


def _migrate_eligible_passengers_phone() -> None:
    try:
        insp = inspect(db.engine)
        if "eligible_passengers" not in insp.get_table_names():
            return
        existing = {c["name"] for c in insp.get_columns("eligible_passengers")}
        if "phone" not in existing:
            try:
                db.session.execute(
                    db.text(
                        "ALTER TABLE eligible_passengers ADD COLUMN phone "
                        "VARCHAR(32) NOT NULL DEFAULT ''"
                    )
                )
                db.session.commit()
            except Exception:
                db.session.rollback()
    except Exception:
        pass


def _normalize_pnr(raw: str) -> str:
    return "".join((raw or "").upper().split())


def _save_complaint_upload(file_storage, allowed_exts):
    if not file_storage or not file_storage.filename:
        return None, None
    raw = secure_filename(file_storage.filename)
    if "." not in raw:
        return None, "Uploaded files must include an extension (e.g. .mp3, .jpg)."
    ext = raw.rsplit(".", 1)[-1].lower()
    if ext not in allowed_exts:
        return None, f"File type .{ext} is not allowed for this upload."
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = UPLOAD_DIR / f"{uuid.uuid4().hex}.{ext}"
    file_storage.save(path)
    return str(path), None


def _attachment_accessible_by_user(fname: str, user: User, is_admin: bool) -> bool:
    q = Complaint.query if is_admin else Complaint.query.filter_by(user_id=user.id)
    for c in q:
        for _k, v in c.attachment_filenames().items():
            if v == fname:
                return True
    return False


def _ensure_admin() -> None:
    if User.query.filter_by(username="admin").first():
        return
    admin = User(username="admin", is_admin=True)
    admin.set_password("admin")
    db.session.add(admin)
    db.session.commit()


def register_routes(app: Flask) -> None:
    @app.route("/")
    def home():
        return render_template("home.html")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            if not username or not password:
                flash("Name and password are required.", "error")
                return render_template("register.html")
            if User.query.filter_by(username=username).first():
                flash("That name is already registered. Please log in.", "error")
                return render_template("register.html")
            if username.lower() == "admin":
                flash("This username is reserved.", "error")
                return render_template("register.html")
            u = User(username=username, is_admin=False)
            u.set_password(password)
            db.session.add(u)
            db.session.commit()
            flash("Registration successful. Please log in.", "success")
            return redirect(url_for("login_user"))
        return render_template("register.html")

    @app.route("/login/user", methods=["GET", "POST"])
    def login_user():
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            user = User.query.filter_by(username=username).first()
            if not user or user.is_admin or not user.check_password(password):
                flash("Invalid username or password.", "error")
                return render_template("login_user.html")
            session.clear()
            session["user_id"] = user.id
            session["is_admin"] = False
            return redirect(url_for("user_dashboard"))
        return render_template("login_user.html")

    @app.route("/login/admin", methods=["GET", "POST"])
    def login_admin():
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            user = User.query.filter_by(username=username).first()
            if not user or not user.is_admin or not user.check_password(password):
                flash("Invalid admin credentials.", "error")
                return render_template("login_admin.html")
            session.clear()
            session["user_id"] = user.id
            session["is_admin"] = True
            return redirect(url_for("admin_dashboard"))
        return render_template("login_admin.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("home"))

    def current_user():
        uid = session.get("user_id")
        if not uid:
            return None
        return db.session.get(User, uid)

    def verified_manifest_row(user: User) -> Optional[EligiblePassenger]:
        mid = session.get("manifest_row_id")
        if not mid:
            return None
        row = db.session.get(EligiblePassenger, int(mid))
        if not row or (row.username or "").lower() != (user.username or "").lower():
            session.pop("manifest_row_id", None)
            return None
        return row

    @app.route("/user/verify-manifest", methods=["POST"])
    def verify_manifest():
        user = current_user()
        if not user or session.get("is_admin"):
            flash("Please log in as a user.", "error")
            return redirect(url_for("login_user"))
        pnr = _normalize_pnr(request.form.get("pnr") or "")
        if not pnr:
            flash("Enter your PNR.", "error")
            return redirect(url_for("user_dashboard"))
        row = EligiblePassenger.query.filter(
            func.lower(EligiblePassenger.username) == (user.username or "").lower(),
            EligiblePassenger.pnr == pnr,
        ).first()
        if not row:
            flash(
                "PNR not found for your account. Only passengers listed by admin "
                "can file complaints — check your PNR or contact support.",
                "error",
            )
            return redirect(url_for("user_dashboard"))
        session["manifest_row_id"] = row.id
        flash("PNR verified. Your journey details are shown below.", "success")
        return redirect(url_for("user_dashboard"))

    @app.route("/user/clear-manifest", methods=["POST"])
    def clear_manifest():
        user = current_user()
        if not user or session.get("is_admin"):
            flash("Please log in as a user.", "error")
            return redirect(url_for("login_user"))
        session.pop("manifest_row_id", None)
        flash("PNR cleared. Enter another PNR to continue.", "info")
        return redirect(url_for("user_dashboard"))

    @app.route("/user/sos", methods=["POST"])
    def user_sos():
        user = current_user()
        if not user or session.get("is_admin"):
            return jsonify(ok=False, error="Please log in as a user."), 403
        manifest = verified_manifest_row(user)
        if not manifest:
            return jsonify(ok=False, error="Verify your PNR before using SOS."), 403
        if not request.is_json:
            return jsonify(ok=False, error="Invalid request."), 400
        data = request.get_json(silent=True) or {}
        if not data.get("token") or data.get("token") != session.get("sos_csrf"):
            return jsonify(
                ok=False, error="Invalid or expired token. Refresh this page and try again."
            ), 403
        now = time.time()
        last = float(session.get("sos_last_ts") or 0)
        if now - last < SOS_COOLDOWN_SEC:
            wait = int(SOS_COOLDOWN_SEC - (now - last)) + 1
            return jsonify(
                ok=False,
                error=f"Please wait {wait} seconds before sending another SOS.",
            ), 429
        try:
            lat = float(data["latitude"])
            lon = float(data["longitude"])
        except (KeyError, TypeError, ValueError):
            return jsonify(ok=False, error="Missing or invalid location."), 400
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return jsonify(ok=False, error="Invalid coordinates."), 400
        acc_raw = data.get("accuracy")
        acc_m = None
        if acc_raw is not None:
            try:
                acc_m = float(acc_raw)
            except (TypeError, ValueError):
                acc_m = None
        ok_send, err_msg, payload = send_sos_notifications(
            manifest, user.username, lat, lon, acc_m
        )
        if not ok_send:
            return jsonify(ok=False, error=err_msg), 503
        session["sos_last_ts"] = now
        new_tok = secrets.token_urlsafe(24)
        session["sos_csrf"] = new_tok
        summary = payload.get("summary") or "alert channels"
        ch = payload.get("channels") or {}
        detail_parts = []
        if ch.get("email", {}).get("ok"):
            detail_parts.append("email sent")
        if ch.get("ntfy", {}).get("ok"):
            detail_parts.append("push sent (ntfy)")
        return jsonify(
            ok=True,
            message=f"SOS sent via: {summary}.",
            token=new_tok,
            twilio_sid=payload.get("twilio_sms_sid"),
            twilio_whatsapp_sid=payload.get("twilio_whatsapp_sid"),
            twilio_to=payload.get("twilio_to"),
            delivery_help=(
                (" · ".join(detail_parts) + " · ") if detail_parts else ""
            )
            + "SMS is shortened for Twilio Trial (1 segment). Full text on WhatsApp/email/ntfy if configured. "
            "Twilio: Monitor → Logs for errors.",
        )

    @app.route("/user/dashboard", methods=["GET", "POST"])
    def user_dashboard():
        user = current_user()
        if not user or session.get("is_admin"):
            flash("Please log in as a user.", "error")
            return redirect(url_for("login_user"))
        manifest = verified_manifest_row(user)
        if request.method == "POST":
            if not manifest:
                flash(
                    "Verify your PNR first. Only registered journey passengers may file complaints.",
                    "error",
                )
                return redirect(url_for("user_dashboard"))
            text = (request.form.get("complaint_text") or "").strip()

            image_path, err = _save_complaint_upload(
                request.files.get("complaint_image"), ALLOWED_IMAGE_EXT
            )
            if err:
                flash(err, "error")
                return redirect(url_for("user_dashboard"))

            audio_path, err = _save_complaint_upload(
                request.files.get("complaint_audio"), ALLOWED_AUDIO_EXT
            )
            if err:
                flash(err, "error")
                return redirect(url_for("user_dashboard"))

            video_path, err = _save_complaint_upload(
                request.files.get("complaint_video"), ALLOWED_VIDEO_EXT
            )
            if err:
                flash(err, "error")
                return redirect(url_for("user_dashboard"))

            if not text and not (image_path or audio_path or video_path):
                flash(
                    "Add a written complaint and/or attach an image, voice recording, or video.",
                    "error",
                )
                return redirect(url_for("user_dashboard"))

            fields, short_msg = analyze_for_complaint(
                text,
                image_path=image_path,
                audio_path=audio_path,
                video_path=video_path,
            )

            attachments = {}
            if image_path:
                attachments["image"] = Path(image_path).name
            if audio_path:
                attachments["audio"] = Path(audio_path).name
            if video_path:
                attachments["video"] = Path(video_path).name
            attachments_json = json.dumps(attachments) if attachments else None

            display_text = text or ""

            comp = Complaint(
                user_id=user.id,
                text=display_text,
                category=fields["category"],
                department=fields["department"],
                priority=fields["priority"],
                sentiment=fields["sentiment"],
                summary=fields["summary"],
                attachments_json=attachments_json,
                status="pending",
                booking_pnr=manifest.pnr,
                booking_train=manifest.train_name,
                booking_location=manifest.location,
                booking_seat=manifest.seat,
                booking_email=manifest.email,
                booking_phone=(manifest.phone or None),
            )
            db.session.add(comp)
            db.session.commit()
            flash(f"Complaint filed. {short_msg}", "success")
            return redirect(url_for("user_dashboard"))
        complaints = (
            Complaint.query.filter_by(user_id=user.id)
            .order_by(Complaint.created_at.desc())
            .all()
        )
        cids = [c.id for c in complaints]
        feedback_rows = (
            Feedback.query.filter(Feedback.complaint_id.in_(cids)).all() if cids else []
        )
        feedback_by_complaint = {f.complaint_id: f for f in feedback_rows}
        sos_token = None
        if manifest:
            sos_token = secrets.token_urlsafe(24)
            session["sos_csrf"] = sos_token
        return render_template(
            "user_dashboard.html",
            user=user,
            complaints=complaints,
            feedback_by_complaint=feedback_by_complaint,
            manifest=manifest,
            sos_token=sos_token,
        )

    @app.route("/user/feedback", methods=["POST"])
    def submit_feedback():
        user = current_user()
        if not user or session.get("is_admin"):
            flash("Please log in as a user.", "error")
            return redirect(url_for("login_user"))
        try:
            cid = int(request.form.get("complaint_id", 0))
        except (TypeError, ValueError):
            cid = 0
        rating_raw = request.form.get("rating", "")
        try:
            rating = int(rating_raw)
        except (TypeError, ValueError):
            rating = 0
        comment = (request.form.get("comment") or "").strip()
        if not cid or rating < 1 or rating > 5:
            flash("Please choose a rating from 1 to 5 stars.", "error")
            return redirect(url_for("user_dashboard"))
        comp = db.session.get(Complaint, cid)
        if not comp or comp.user_id != user.id:
            flash("Invalid complaint.", "error")
            return redirect(url_for("user_dashboard"))
        if comp.status != "resolved":
            flash("Feedback is only available after your complaint is marked resolved.", "error")
            return redirect(url_for("user_dashboard"))
        if Feedback.query.filter_by(complaint_id=cid).first():
            flash("You already submitted feedback for this complaint.", "error")
            return redirect(url_for("user_dashboard"))
        from ml_sentiment import predict_sentiment
        # 1. Start with ML model prediction for the text
        sentiment = predict_sentiment(comment) if comment else "Neutral"
        
        # 2. Heuristic Override: If text is ambiguous (Neutral), use the star rating as the tie-breaker
        # 4-5 stars = Positive, 1-2 stars = Negative, 3 stars = Neutral
        if sentiment == "Neutral":
            if rating >= 4:
                sentiment = "Positive"
            elif rating <= 2:
                sentiment = "Negative"
                
        db.session.add(
            Feedback(
                complaint_id=cid,
                user_id=user.id,
                rating=rating,
                comment=comment or None,
                sentiment=sentiment,
            )
        )
        db.session.commit()
        flash("Thank you — your feedback helps us improve RailMadad.", "success")
        return redirect(url_for("user_dashboard"))

    @app.route("/attachment/<path:fname>")
    def serve_attachment(fname):
        u = current_user()
        if not u:
            abort(403)
        if not _attachment_accessible_by_user(
            fname, u, bool(session.get("is_admin"))
        ):
            abort(403)
        target = (UPLOAD_DIR / fname).resolve()
        try:
            target.relative_to(UPLOAD_DIR.resolve())
        except ValueError:
            abort(404)
        if not target.is_file():
            abort(404)
        return send_from_directory(UPLOAD_DIR, fname)

    def _admin_queue_active_count() -> int:
        return Complaint.query.filter(Complaint.status != "resolved").count()

    @app.route("/admin/manifest", methods=["GET", "POST"])
    def admin_manifest():
        user = current_user()
        if not user or not session.get("is_admin"):
            flash("Please log in as admin.", "error")
            return redirect(url_for("login_admin"))

        def _fields():
            return (
                (request.form.get("username") or "").strip(),
                _normalize_pnr(request.form.get("pnr") or ""),
                (request.form.get("train_name") or "").strip(),
                (request.form.get("location") or "").strip(),
                (request.form.get("seat") or "").strip(),
                (request.form.get("email") or "").strip(),
                (request.form.get("phone") or "").strip(),
            )

        if request.method == "POST":
            action = (request.form.get("action") or "").strip()
            if action == "add":
                (
                    username,
                    pnr,
                    train_name,
                    location,
                    seat,
                    email,
                    phone,
                ) = _fields()
                if not all(
                    [username, pnr, train_name, location, seat, email, phone]
                ):
                    flash("All manifest fields are required.", "error")
                    return redirect(url_for("admin_manifest"))
                if EligiblePassenger.query.filter_by(pnr=pnr).first():
                    flash("That PNR is already in the manifest.", "error")
                    return redirect(url_for("admin_manifest"))
                db.session.add(
                    EligiblePassenger(
                        username=username,
                        pnr=pnr,
                        train_name=train_name,
                        location=location,
                        seat=seat,
                        email=email,
                        phone=phone,
                    )
                )
                db.session.commit()
                flash("Passenger added to manifest.", "success")
            elif action == "update":
                try:
                    eid = int(request.form.get("id", 0))
                except (TypeError, ValueError):
                    eid = 0
                row = db.session.get(EligiblePassenger, eid) if eid else None
                if not row:
                    flash("Record not found.", "error")
                    return redirect(url_for("admin_manifest"))
                (
                    username,
                    pnr,
                    train_name,
                    location,
                    seat,
                    email,
                    phone,
                ) = _fields()
                if not all(
                    [username, pnr, train_name, location, seat, email, phone]
                ):
                    flash("All manifest fields are required.", "error")
                    return redirect(
                        url_for("admin_manifest", manifest_edit=row.id)
                    )
                clash = EligiblePassenger.query.filter(
                    EligiblePassenger.pnr == pnr, EligiblePassenger.id != row.id
                ).first()
                if clash:
                    flash("That PNR is already used by another row.", "error")
                    return redirect(
                        url_for("admin_manifest", manifest_edit=row.id)
                    )
                row.username = username
                row.pnr = pnr
                row.train_name = train_name
                row.location = location
                row.seat = seat
                row.email = email
                row.phone = phone
                db.session.commit()
                flash("Manifest entry updated.", "success")
            elif action == "delete":
                try:
                    eid = int(request.form.get("id", 0))
                except (TypeError, ValueError):
                    eid = 0
                row = db.session.get(EligiblePassenger, eid) if eid else None
                if row:
                    db.session.delete(row)
                    db.session.commit()
                    flash("Removed from manifest.", "success")
            return redirect(url_for("admin_manifest"))

        manifest_rows = EligiblePassenger.query.order_by(
            EligiblePassenger.username, EligiblePassenger.pnr
        ).all()
        edit_mid = request.args.get("manifest_edit", type=int)
        edit_manifest_row = (
            db.session.get(EligiblePassenger, edit_mid) if edit_mid else None
        )
        return render_template(
            "admin_manifest.html",
            user=user,
            manifest_rows=manifest_rows,
            edit_manifest_row=edit_manifest_row,
            queue_active_count=_admin_queue_active_count(),
        )

    @app.route("/admin/dashboard", methods=["GET"])
    def admin_dashboard():
        user = current_user()
        if not user or not session.get("is_admin"):
            flash("Please log in as admin.", "error")
            return redirect(url_for("login_admin"))
        ordered = Complaint.query.order_by(Complaint.created_at.desc()).all()
        total_complaints = len(ordered)
        status_counts = Counter(c.status for c in ordered)
        count_pending = status_counts.get("pending", 0)
        count_in_progress = status_counts.get("in_progress", 0)
        count_resolved = status_counts.get("resolved", 0)

        def _norm_category(c: Complaint) -> str:
            s = (c.category or "").strip()
            return s if s else "Others"

        cat_counts = Counter(_norm_category(c) for c in ordered)
        category_rows = sorted(
            cat_counts.items(), key=lambda x: (-x[1], x[0].lower())
        )
        category_max = max((n for _, n in category_rows), default=0)

        return render_template(
            "admin_dashboard.html",
            user=user,
            total_complaints=total_complaints,
            count_pending=count_pending,
            count_in_progress=count_in_progress,
            count_resolved=count_resolved,
            category_rows=category_rows,
            category_max=category_max,
            queue_active_count=_admin_queue_active_count(),
        )

    @app.route("/admin/queue", methods=["GET", "POST"])
    def admin_queue():
        user = current_user()
        if not user or not session.get("is_admin"):
            flash("Please log in as admin.", "error")
            return redirect(url_for("login_admin"))
        if request.method == "POST":
            cid = request.form.get("complaint_id")
            new_status = (request.form.get("status") or "").strip()
            allowed = {"pending", "in_progress", "resolved"}
            if cid and new_status in allowed:
                comp = db.session.get(Complaint, int(cid))
                if comp:
                    comp.status = new_status
                    db.session.commit()
                    flash("Status updated.", "success")
            return redirect(url_for("admin_queue"))
        ordered = (
            Complaint.query.options(joinedload(Complaint.feedback))
            .order_by(Complaint.created_at.desc())
            .all()
        )
        active_complaints = [c for c in ordered if c.status != "resolved"]
        resolved_complaints = [c for c in ordered if c.status == "resolved"]
        return render_template(
            "admin_queue.html",
            user=user,
            active_complaints=active_complaints,
            resolved_complaints=resolved_complaints,
            queue_active_count=_admin_queue_active_count(),
        )

    @app.route("/admin/insights", methods=["GET"])
    def admin_insights():
        user = current_user()
        if not user or not session.get("is_admin"):
            flash("Please log in as admin.", "error")
            return redirect(url_for("login_admin"))
        resolved_complaints = (
            Complaint.query.options(joinedload(Complaint.feedback))
            .filter_by(status="resolved")
            .all()
        )
        resolved_total = len(resolved_complaints)
        all_feedback = Feedback.query.order_by(Feedback.created_at.desc()).all()
        n_fb = len(all_feedback)
        avg_rating = (
            round(sum(f.rating for f in all_feedback) / n_fb, 2) if n_fb else None
        )
        rating_dist = {
            i: sum(1 for f in all_feedback if f.rating == i) for i in range(1, 6)
        }
        resolved_with_fb = sum(1 for c in resolved_complaints if c.feedback)
        resolved_no_fb = resolved_total - resolved_with_fb
        
        sentiment_counts = {
            "Positive": sum(1 for f in all_feedback if getattr(f, "sentiment", None) == "Positive"),
            "Neutral": sum(1 for f in all_feedback if getattr(f, "sentiment", None) in ("Neutral", None, "")),
            "Negative": sum(1 for f in all_feedback if getattr(f, "sentiment", None) == "Negative"),
        }
        
        return render_template(
            "admin_insights.html",
            user=user,
            all_feedback=all_feedback,
            feedback_count=n_fb,
            avg_rating=avg_rating,
            rating_dist=rating_dist,
            resolved_with_fb=resolved_with_fb,
            resolved_no_fb=resolved_no_fb,
            resolved_total=resolved_total,
            sentiment_counts=sentiment_counts,
            queue_active_count=_admin_queue_active_count(),
        )


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
