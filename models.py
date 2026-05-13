import json
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    complaints = db.relationship(
        "Complaint", backref="user", lazy="dynamic", cascade="all, delete-orphan"
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(
            password, method="pbkdf2:sha256"
        )

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Complaint(db.Model):
    __tablename__ = "complaints"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    text = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(128), nullable=False, default="Others")
    department = db.Column(db.String(256), nullable=False)
    priority = db.Column(db.String(16), nullable=False)  # low, medium, high
    sentiment = db.Column(db.String(32), nullable=False, default="Neutral")
    summary = db.Column(db.Text, nullable=True)
    attachments_json = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(32), nullable=False, default="pending")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Snapshot from verified manifest row when the complaint was filed
    booking_pnr = db.Column(db.String(32), nullable=True)
    booking_train = db.Column(db.String(256), nullable=True)
    booking_location = db.Column(db.String(256), nullable=True)
    booking_seat = db.Column(db.String(64), nullable=True)
    booking_email = db.Column(db.String(256), nullable=True)
    booking_phone = db.Column(db.String(32), nullable=True)

    def attachment_filenames(self):
        if not self.attachments_json:
            return {}
        try:
            data = json.loads(self.attachments_json)
            return {k: v for k, v in data.items() if v}
        except (json.JSONDecodeError, TypeError):
            return {}


class Feedback(db.Model):
    __tablename__ = "feedbacks"

    id = db.Column(db.Integer, primary_key=True)
    complaint_id = db.Column(
        db.Integer, db.ForeignKey("complaints.id"), nullable=False, unique=True, index=True
    )
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text, nullable=True)
    sentiment = db.Column(db.String(32), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    complaint = db.relationship("Complaint", backref=db.backref("feedback", uselist=False))
    user = db.relationship("User", backref="feedbacks")


class EligiblePassenger(db.Model):
    """Admin-managed list: only these username + PNR pairs may file complaints."""

    __tablename__ = "eligible_passengers"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, index=True)
    pnr = db.Column(db.String(32), unique=True, nullable=False, index=True)
    train_name = db.Column(db.String(256), nullable=False)
    location = db.Column(db.String(256), nullable=False)
    seat = db.Column(db.String(64), nullable=False)
    email = db.Column(db.String(256), nullable=False)
    phone = db.Column(db.String(32), nullable=False, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
