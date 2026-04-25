from datetime import datetime
import uuid

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class PDF(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    topic_name = db.Column(db.String(255), nullable=True)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False, unique=True)
    page_count = db.Column(db.Integer)
    file_size = db.Column(db.Integer)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    sessions = db.relationship(
        "QuizSession",
        backref="pdf",
        lazy=True,
        cascade="all, delete-orphan",
    )


class QuizSession(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    pdf_id = db.Column(db.Integer, db.ForeignKey("pdf.id"), nullable=False)
    num_questions = db.Column(db.Integer, default=10)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    questions = db.relationship(
        "Question",
        backref="session",
        lazy=True,
        cascade="all, delete-orphan",
    )
    attempts = db.relationship(
        "QuizAttempt",
        backref="session",
        lazy=True,
        cascade="all, delete-orphan",
    )


class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(36), db.ForeignKey("quiz_session.id"), nullable=False)
    order = db.Column(db.Integer, nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    option_a = db.Column(db.Text, nullable=False)
    option_b = db.Column(db.Text, nullable=False)
    option_c = db.Column(db.Text, nullable=False)
    option_d = db.Column(db.Text, nullable=False)
    correct_answer = db.Column(db.String(1), nullable=False)
    explanation = db.Column(db.Text)


class QuizAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(36), db.ForeignKey("quiz_session.id"), nullable=False)
    score = db.Column(db.Integer, nullable=False)
    total = db.Column(db.Integer, nullable=False)
    answers = db.Column(db.Text)  # JSON string
    completed_at = db.Column(db.DateTime, default=datetime.utcnow)
